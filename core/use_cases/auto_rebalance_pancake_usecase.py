from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from web3 import Web3
from web3.contract import Contract

from adapters.chain.client_vault import ClientVaultAdapter
from adapters.external.database.mongo_client import get_mongo_db
from adapters.external.database.vault_client_registry_repository_mongodb import VaultRegistryRepositoryMongoDB
from config import get_settings
from core.domain.entities.vault_client_registry_entity import VaultRegistryEntity
from core.domain.repositories.vault_client_registry_repository_interface import VaultRegistryRepositoryInterface
from core.services.tx_service import TxService
from core.services.utils import to_json_safe


ABI_ERC20_MIN = [
    {"name": "decimals", "outputs": [{"type": "uint8"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "symbol", "outputs": [{"type": "string"}], "inputs": [], "stateMutability": "view", "type": "function"},
]

ABI_PANCAKE_V3_POOL_MIN = [
    {"name": "token0", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token1", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "fee", "outputs": [{"type": "uint24"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "tickSpacing", "outputs": [{"type": "int24"}], "inputs": [], "stateMutability": "view", "type": "function"},
]


USD_SYMBOLS = {"USDC", "USDT", "DAI", "USD+", "USDB", "USDE"}


def _price_to_tick(p_t1_t0: float, dec0: int, dec1: int) -> int:
    """
    Convert p_t1_t0 (token1 per token0, in human units) to UniswapV3/PancakeV3 tick.

    IMPORTANT:
    - Uniswap/Pancake tick uses raw price token1/token0, where amounts are in raw units.
    - Therefore: p_raw = p_human * 10^(dec1 - dec0)
    """
    if p_t1_t0 <= 0:
        raise ValueError("price must be > 0")

    p_raw = float(p_t1_t0) * (10 ** (dec1 - dec0))
    return int(math.floor(math.log(p_raw) / math.log(1.0001)))


def _align_floor(t: int, spacing: int) -> int:
    r = t % spacing
    return t - r


def _align_ceil(t: int, spacing: int) -> int:
    r = t % spacing
    return t if r == 0 else t + (spacing - r)


def _is_usd(sym: str) -> bool:
    return (sym or "").upper() in USD_SYMBOLS


def _ui_price_to_p_t1_t0(ui_price: float, sym0: str, sym1: str) -> float:
    """
    Convert a UI price (usually 'USD per RISK') into p_t1_t0 (token1 per token0) expected by price->tick.

    Rules (same as your old endpoint):
    - If token1 is USD-like => UI price already equals p_t1_t0 (token1/token0).
    - If token0 is USD-like => UI price is p_t0_t1 => invert.
    - Otherwise => assume UI already matches pool convention.
    """
    if _is_usd(sym1):
        return float(ui_price)
    if _is_usd(sym0):
        return 1.0 / float(ui_price)
    return float(ui_price)


@dataclass
class AutoRebalancePancakeUseCase:
    w3: Web3
    txs: TxService
    vault_registry_repo: VaultRegistryRepositoryInterface

    @classmethod
    def from_settings(cls) -> "AutoRebalancePancakeUseCase":
        s = get_settings()
        w3 = Web3(Web3.HTTPProvider(s.RPC_URL_DEFAULT))
        txs = TxService(s.RPC_URL_DEFAULT)

        db = get_mongo_db()
        repo = VaultRegistryRepositoryMongoDB(db[VaultRegistryRepositoryMongoDB.COLLECTION])
        repo.ensure_indexes()

        return cls(w3=w3, txs=txs, vault_registry_repo=repo)

    def _get_vault_by_alias(self, alias: str) -> VaultRegistryEntity:
        alias = (alias or "").strip()
        if not alias:
            raise ValueError("alias is required")

        ent = self.vault_registry_repo.find_by_alias(alias)
        if not ent:
            raise ValueError(f"Unknown vault alias: {alias}")
        return ent

    def _erc20(self, addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_ERC20_MIN)

    def _pool_contract(self, pool_addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(pool_addr), abi=ABI_PANCAKE_V3_POOL_MIN)

    def _pool_meta(self, pool_addr: str) -> Dict[str, Any]:
        pool = self._pool_contract(pool_addr)

        token0 = Web3.to_checksum_address(pool.functions.token0().call())
        token1 = Web3.to_checksum_address(pool.functions.token1().call())

        erc0 = self._erc20(token0)
        erc1 = self._erc20(token1)

        dec0 = int(erc0.functions.decimals().call())
        dec1 = int(erc1.functions.decimals().call())

        try:
            sym0 = str(erc0.functions.symbol().call())
        except Exception:
            sym0 = "TOKEN0"
        try:
            sym1 = str(erc1.functions.symbol().call())
        except Exception:
            sym1 = "TOKEN1"

        spacing = int(pool.functions.tickSpacing().call())
        fee = int(pool.functions.fee().call())

        return {
            "token0": token0,
            "token1": token1,
            "dec0": dec0,
            "dec1": dec1,
            "sym0": sym0,
            "sym1": sym1,
            "spacing": spacing,
            "fee": fee,
        }

    def _resolve_range_ticks(
        self,
        *,
        pool_addr: str,
        new_lower: Optional[int],
        new_upper: Optional[int],
        lower_price: Optional[float],
        upper_price: Optional[float],
    ) -> Tuple[int, int, Dict[str, Any]]:
        meta = self._pool_meta(pool_addr)
        dec0 = int(meta["dec0"])
        dec1 = int(meta["dec1"])
        sym0 = str(meta["sym0"])
        sym1 = str(meta["sym1"])
        spacing = int(meta["spacing"] or 0)

        # ticks directly provided
        if new_lower is not None and new_upper is not None:
            lower_tick = int(new_lower)
            upper_tick = int(new_upper)
        else:
            if lower_price is None or upper_price is None:
                raise ValueError("You must provide either (new_lower and new_upper) OR (lower_price and upper_price).")

            pL = _ui_price_to_p_t1_t0(float(lower_price), sym0, sym1)
            pU = _ui_price_to_p_t1_t0(float(upper_price), sym0, sym1)

            lower_tick = _price_to_tick(pL, dec0, dec1)
            upper_tick = _price_to_tick(pU, dec0, dec1)

        # ensure ascending
        if lower_tick > upper_tick:
            lower_tick, upper_tick = upper_tick, lower_tick

        # align spacing
        if spacing:
            lower_tick = _align_floor(lower_tick, spacing)
            upper_tick = _align_ceil(upper_tick, spacing)

        # avoid collapse
        if lower_tick == upper_tick:
            step = spacing or 1
            lower_tick -= step
            upper_tick += step

        if int(lower_tick) >= int(upper_tick):
            raise ValueError("Resolved ticks invalid (lower >= upper). Check provided prices.")

        debug = {
            "sym0": sym0,
            "sym1": sym1,
            "dec0": dec0,
            "dec1": dec1,
            "spacing": spacing,
        }
        return int(lower_tick), int(upper_tick), debug

    def auto_rebalance_pancake(
        self,
        *,
        alias: str,
        new_lower: Optional[int],
        new_upper: Optional[int],
        lower_price: Optional[float],
        upper_price: Optional[float],
        fee: Optional[int],
        token_in: str,
        token_out: str,
        swap_amount_in: int,
        swap_amount_out_min: int,
        sqrt_price_limit_x96: int = 0,
        gas_strategy: str = "buffered",
    ) -> Dict[str, Any]:
        ent = self._get_vault_by_alias(alias)

        dex = (ent.dex or "").strip().lower()
        if dex != "pancake":
            raise ValueError(f"Vault dex mismatch. expected=pancake got={dex}")

        vault_addr = (ent.config.address or "").strip()
        if not (isinstance(vault_addr, str) and vault_addr.startswith("0x") and len(vault_addr) == 42):
            raise ValueError("Vault address not found in registry config.address")

        pool_addr = (getattr(ent.config, "pool", None) or "").strip()
        if not (isinstance(pool_addr, str) and pool_addr.startswith("0x") and len(pool_addr) == 42):
            raise ValueError("Pool address not found in registry config.pool (required for price->tick and fee inference)")

        lower_tick, upper_tick, range_dbg = self._resolve_range_ticks(
            pool_addr=pool_addr,
            new_lower=new_lower,
            new_upper=new_upper,
            lower_price=lower_price,
            upper_price=upper_price,
        )

        # infer fee from pool if missing
        if fee is None:
            fee = int(self._pool_meta(pool_addr)["fee"])

        if swap_amount_in > 0 and (fee is None or int(fee) <= 0):
            raise ValueError("fee is required (or inferable) when swap_amount_in > 0")

        cv = ClientVaultAdapter(w3=self.w3, address=vault_addr)

        fn = cv.fn_auto_rebalance_pancake(
            new_lower=int(lower_tick),
            new_upper=int(upper_tick),
            fee=int(fee),
            token_in=token_in,
            token_out=token_out,
            swap_amount_in=int(swap_amount_in),
            swap_amount_out_min=int(swap_amount_out_min),
            sqrt_price_limit_x96=int(sqrt_price_limit_x96 or 0),
        )

        tx_any = self.txs.send(fn, wait=True, gas_strategy=gas_strategy)
        return to_json_safe(
            {
                "tx": tx_any,
                "alias": ent.alias,
                "vault_address": Web3.to_checksum_address(vault_addr),
                "pool_address": Web3.to_checksum_address(pool_addr),
                "range_used": {"lower_tick": int(lower_tick), "upper_tick": int(upper_tick)},
                "fee_used": int(fee),
                "range_debug": range_dbg,
            }
        )
