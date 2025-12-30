from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Dict, Tuple

from web3 import Web3

from adapters.chain.client_vault import ClientVaultAdapter
from adapters.chain.cl_adapter import CLAdapter

getcontext().prec = 90
Q96 = Decimal(2) ** 96
U128_MAX = (1 << 128) - 1


ABI_ERC20 = [
    {"name": "decimals", "outputs": [{"type": "uint8"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "symbol", "outputs": [{"type": "string"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "balanceOf", "outputs": [{"type": "uint256"}], "inputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

ABI_NFPM = [
    {
        "name": "positions",
        "inputs": [{"type": "uint256", "name": "tokenId"}],
        "outputs": [
            {"type": "uint96"},   # nonce
            {"type": "address"},  # operator
            {"type": "address"},  # token0
            {"type": "address"},  # token1
            {"type": "uint24"},   # fee
            {"type": "int24"},    # tickLower
            {"type": "int24"},    # tickUpper
            {"type": "uint128"},  # liquidity
            {"type": "uint256"},  # feeGrowthInside0LastX128
            {"type": "uint256"},  # feeGrowthInside1LastX128
            {"type": "uint128"},  # tokensOwed0
            {"type": "uint128"},  # tokensOwed1
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "collect",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "recipient", "type": "address"},
                    {"name": "amount0Max", "type": "uint128"},
                    {"name": "amount1Max", "type": "uint128"},
                ],
            }
        ],
        "outputs": [{"type": "uint256", "name": "amount0"}, {"type": "uint256", "name": "amount1"}],
        "stateMutability": "payable",
        "type": "function",
    },
]


def _price_from_sqrtPriceX96(sqrtP: int, dec0: int, dec1: int) -> float:
    ratio = Decimal(sqrtP) / Q96
    px = ratio * ratio
    scale = Decimal(10) ** (dec0 - dec1)
    return float(px * scale)  # token1 per token0


def _prices_from_tick(tick: int, dec0: int, dec1: int) -> Dict[str, float]:
    p_t1_t0 = (Decimal("1.0001") ** Decimal(tick)) * (Decimal(10) ** Decimal(dec0 - dec1))
    p_t1_t0_f = float(p_t1_t0)
    p_t0_t1_f = float("inf") if p_t1_t0_f == 0 else float(1.0 / p_t1_t0_f)
    return {"tick": int(tick), "p_t1_t0": p_t1_t0_f, "p_t0_t1": p_t0_t1_f}


def _get_sqrt_ratio_at_tick(tick: int) -> int:
    # aproximação suficiente pro painel (não precisa bitmath exata)
    # sqrt(1.0001^tick) * Q96
    val = (Decimal("1.0001") ** (Decimal(tick) / 2)) * Q96
    return int(val)


def _get_amounts_for_liquidity(sqrtP: int, sqrtA: int, sqrtB: int, L: int) -> Tuple[int, int]:
    sp = Decimal(sqrtP)
    sa = Decimal(sqrtA)
    sb = Decimal(sqrtB)
    liq = Decimal(L)

    if sa > sb:
        sa, sb = sb, sa

    if sp <= sa:
        # amount0 only
        amount0 = liq * (sb - sa) / (sa * sb)
        return int(amount0), 0

    if sp < sb:
        amount0 = liq * (sb - sp) / (sp * sb)
        amount1 = liq * (sp - sa)
        return int(amount0), int(amount1)

    # sp >= sb => amount1 only
    amount1 = liq * (sb - sa)
    return 0, int(amount1)


@dataclass
class VaultStatusService:
    w3: Web3

    def _erc20(self, addr: str):
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_ERC20)

    def _nfpm(self, addr: str):
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_NFPM)

    def compute(self, vault_address: str) -> Dict:
        vault = ClientVaultAdapter(w3=self.w3, address=vault_address)

        owner = vault.owner()
        executor = vault.executor()
        adapter_addr = vault.adapter()
        dex_router = vault.dex_router()
        fee_collector = vault.fee_collector()
        strategy_id = vault.strategy_id()
        last_rebalance_ts = vault.last_rebalance_ts()

        ad = CLAdapter(w3=self.w3, address=adapter_addr)
        pool = ad.pool()
        nfpm_addr = ad.nfpm()
        gauge = ad.gauge()
        tick_spacing = ad.tick_spacing()

        sqrt_price_x96, tick = ad.slot0()

        # token pair (prefer adapter.tokens())
        t0, t1 = ad.tokens()

        e0 = self._erc20(t0)
        e1 = self._erc20(t1)

        dec0 = int(e0.functions.decimals().call())
        dec1 = int(e1.functions.decimals().call())
        try:
            sym0 = e0.functions.symbol().call()
        except Exception:
            sym0 = "T0"
        try:
            sym1 = e1.functions.symbol().call()
        except Exception:
            sym1 = "T1"

        # tokenId (prefer adapter.currentTokenId(vault))
        token_id = ad.current_token_id(vault_address)
        # fallback: vault.positionTokenId()
        if not token_id:
            token_id = vault.position_token_id()

        lower_tick = upper_tick = 0
        liquidity = 0

        fees0_raw = 0
        fees1_raw = 0

        if token_id:
            nfpm = self._nfpm(nfpm_addr)
            pos = nfpm.functions.positions(int(token_id)).call()
            lower_tick = int(pos[5])
            upper_tick = int(pos[6])
            liquidity = int(pos[7])

            # fee preview (collect call)
            try:
                fees0_raw, fees1_raw = nfpm.functions.collect(
                    (int(token_id), Web3.to_checksum_address(vault_address), int(U128_MAX), int(U128_MAX))
                ).call()
            except Exception:
                fees0_raw, fees1_raw = 0, 0

        # holdings: idle balances in vault + estimate in-position from liquidity & ticks
        bal0_idle_raw = int(e0.functions.balanceOf(Web3.to_checksum_address(vault_address)).call())
        bal1_idle_raw = int(e1.functions.balanceOf(Web3.to_checksum_address(vault_address)).call())

        vault_idle0 = float(Decimal(bal0_idle_raw) / (Decimal(10) ** dec0))
        vault_idle1 = float(Decimal(bal1_idle_raw) / (Decimal(10) ** dec1))

        inpos0 = 0.0
        inpos1 = 0.0
        if token_id and liquidity and lower_tick != upper_tick:
            sqrtA = _get_sqrt_ratio_at_tick(lower_tick)
            sqrtB = _get_sqrt_ratio_at_tick(upper_tick)
            amt0_raw, amt1_raw = _get_amounts_for_liquidity(sqrt_price_x96, sqrtA, sqrtB, liquidity)
            inpos0 = float(Decimal(amt0_raw) / (Decimal(10) ** dec0))
            inpos1 = float(Decimal(amt1_raw) / (Decimal(10) ** dec1))

        totals0 = vault_idle0 + inpos0
        totals1 = vault_idle1 + inpos1

        # prices panel
        current_block = _prices_from_tick(tick, dec0, dec1)
        lower_block = _prices_from_tick(lower_tick, dec0, dec1) if token_id else _prices_from_tick(tick, dec0, dec1)
        upper_block = _prices_from_tick(upper_tick, dec0, dec1) if token_id else _prices_from_tick(tick, dec0, dec1)

        # range flags
        out_of_range = False
        range_side = "inside"
        if token_id:
            out_of_range = tick < lower_tick or tick >= upper_tick
            range_side = "inside"
            if out_of_range:
                range_side = "below" if tick < lower_tick else "above"

        return {
            "vault": Web3.to_checksum_address(vault_address),

            "owner": owner,
            "executor": executor,
            "adapter": Web3.to_checksum_address(adapter_addr),
            "dex_router": Web3.to_checksum_address(dex_router),
            "fee_collector": Web3.to_checksum_address(fee_collector),
            "strategy_id": int(strategy_id),

            "pool": Web3.to_checksum_address(pool),
            "nfpm": Web3.to_checksum_address(nfpm_addr),
            "gauge": Web3.to_checksum_address(gauge) if gauge and gauge != "0x0000000000000000000000000000000000000000" else "0x0000000000000000000000000000000000000000",

            "token0": {"address": Web3.to_checksum_address(t0), "symbol": sym0, "decimals": dec0},
            "token1": {"address": Web3.to_checksum_address(t1), "symbol": sym1, "decimals": dec1},

            "position_token_id": int(token_id),
            "liquidity": int(liquidity),
            "lower_tick": int(lower_tick),
            "upper_tick": int(upper_tick),
            "tick_spacing": int(tick_spacing),

            "tick": int(tick),
            "sqrt_price_x96": int(sqrt_price_x96),
            "prices": {"current": current_block, "lower": lower_block, "upper": upper_block},

            "out_of_range": bool(out_of_range),
            "range_side": range_side,

            "holdings": {
                "vault_idle": {"token0": vault_idle0, "token1": vault_idle1},
                "in_position": {"token0": inpos0, "token1": inpos1},
                "totals": {"token0": totals0, "token1": totals1},
            },

            "fees_uncollected": {
                "token0": float(Decimal(int(fees0_raw)) / (Decimal(10) ** dec0)),
                "token1": float(Decimal(int(fees1_raw)) / (Decimal(10) ** dec1)),
            },

            "last_rebalance_ts": int(last_rebalance_ts),
        }
