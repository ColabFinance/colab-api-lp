from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Dict, Tuple, Optional, Any

from web3 import Web3
from web3.contract import Contract

from config import get_settings
from adapters.chain.client_vault import ClientVaultAdapter
from adapters.chain.cl_adapter import CLAdapter
from core.domain.entities.vault_client_registry_entity import SwapPoolRef
from core.domain.schemas.onchain_types import (
    Erc20Meta,
    FeesUncollectedOut,
    GaugeRewardBalancesOut,
    GaugeRewardsOut,
    HoldingsBlock,
    HoldingsOut,
    PriceBlock,
    PricesOut,
    VaultStatusOut,
)

getcontext().prec = 90
Q96 = Decimal(2) ** 96
U128_MAX = (1 << 128) - 1
ZERO_ADDR = "0x0000000000000000000000000000000000000000"

USD_SYMBOLS = {"USDC", "USDT", "DAI", "USD+", "USDB", "USDE"}

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
    {
        "name": "ownerOf",
        "inputs": [{"type": "uint256", "name": "tokenId"}],
        "outputs": [{"type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Generic gauge style (Aerodrome-like): earned(account, tokenId) + rewardToken()
ABI_GAUGE_MIN = [
    {
        "name": "earned",
        "inputs": [{"type": "address", "name": "account"}, {"type": "uint256", "name": "tokenId"}],
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {"name": "rewardToken", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

# Pancake MasterChefV3 minimal: pendingCake(tokenId) + CAKE()
ABI_PANCAKE_MASTERCHEF_MIN = [
    {"name": "pendingCake", "inputs": [{"type": "uint256", "name": "tokenId"}], "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"name": "CAKE", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

# V3 pool minimal for CAKE/USDC reference
ABI_V3_POOL_MIN = [
    {"name": "token0", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token1", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {
        "name": "slot0",
        "inputs": [],
        "outputs": [
            {"type": "uint160"},  # sqrtPriceX96
            {"type": "int24"},    # tick
            {"type": "uint16"},   # observationIndex
            {"type": "uint16"},   # observationCardinality
            {"type": "uint16"},   # observationCardinalityNext
            {"type": "uint32"},   # feeProtocol  <-- FIX (was uint8)
            {"type": "bool"},     # unlocked
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


def _is_usd_symbol(sym: str) -> bool:
    return (sym or "").upper() in USD_SYMBOLS


def _is_stable_addr(addr: str) -> bool:
    s = get_settings()
    try:
        return (addr or "").lower() in {a.lower() for a in (s.STABLE_TOKEN_ADDRESSES or [])}
    except Exception:
        return False


def _sqrtPriceX96_to_price_t1_per_t0(sqrtP: int, dec0: int, dec1: int) -> float:
    ratio = Decimal(sqrtP) / Q96
    px = ratio * ratio
    scale = Decimal(10) ** (dec0 - dec1)
    return float(px * scale)  # token1 per token0 (human)


def _prices_from_tick(tick: int, dec0: int, dec1: int) -> Dict[str, float]:
    # IMPORTANT: human token1/token0 uses 10^(dec0-dec1)
    p_t1_t0 = (Decimal("1.0001") ** Decimal(tick)) * (Decimal(10) ** Decimal(dec0 - dec1))
    p_t1_t0_f = float(p_t1_t0)
    p_t0_t1_f = float("inf") if p_t1_t0_f == 0 else float(1.0 / p_t1_t0_f)
    return {"tick": int(tick), "p_t1_t0": p_t1_t0_f, "p_t0_t1": p_t0_t1_f}


def _get_sqrt_ratio_at_tick(tick: int) -> int:
    val = (Decimal("1.0001") ** (Decimal(tick) / 2)) * Q96
    return int(val)


def _get_amounts_for_liquidity(sqrtP: int, sqrtA: int, sqrtB: int, L: int) -> Tuple[int, int]:
    """
    Uniswap v3 math with Q64.96 sqrt prices.
    Returns raw token amounts (uint256-like integers).
    """
    sp = Decimal(sqrtP)
    sa = Decimal(sqrtA)
    sb = Decimal(sqrtB)
    liq = Decimal(L)
    q96 = Q96  # Decimal(2) ** 96

    if sa > sb:
        sa, sb = sb, sa

    if liq <= 0:
        return 0, 0

    if sp <= sa:
        # amount0 = L * (sb - sa) / (sa * sb) * Q96
        amount0 = liq * (sb - sa) * q96 / (sa * sb)
        return int(amount0), 0

    if sp < sb:
        # amount0 = L * (sb - sp) / (sp * sb) * Q96
        amount0 = liq * (sb - sp) * q96 / (sp * sb)
        # amount1 = L * (sp - sa) / Q96
        amount1 = liq * (sp - sa) / q96
        return int(amount0), int(amount1)

    # sp >= sb
    # amount1 = L * (sb - sa) / Q96
    amount1 = liq * (sb - sa) / q96
    return 0, int(amount1)



@dataclass
class VaultStatusService:
    w3: Web3

    def _erc20(self, addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_ERC20)

    def _nfpm(self, addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_NFPM)

    def _v3_pool(self, addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_V3_POOL_MIN)

    def _gauge_generic(self, addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_GAUGE_MIN)

    def _pancake_masterchef(self, addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_PANCAKE_MASTERCHEF_MIN)

    def _pancake_reward_usd_est(
        self,
        *,
        swap_pools: Dict[str, SwapPoolRef],
        pending_amount: float,
        reward_token_addr: str,
    ) -> Optional[float]:
        """
        Estimate CAKE rewards USD using swap_pools['CAKE_USDC'] (or cake_usdc) as reference v3 pool.
        swap_pools entry can be:
          - {'pool': '0x...', ...}
          - or directly '0x...'
        """
        if pending_amount <= 0:
            return 0.0

        ref: SwapPoolRef | None = swap_pools.get("CAKE_USDC") or swap_pools.get("cake_usdc")
        pool_addr = None
        
        if ref is not None:
            pool_addr = ref.pool
        
        if not pool_addr:
            return None

        try:
            pool = self._v3_pool(pool_addr)
            t0 = Web3.to_checksum_address(pool.functions.token0().call())
            t1 = Web3.to_checksum_address(pool.functions.token1().call())

            erc0 = self._erc20(t0)
            erc1 = self._erc20(t1)

            dec0 = int(erc0.functions.decimals().call())
            dec1 = int(erc1.functions.decimals().call())

            try:
                sym0 = str(erc0.functions.symbol().call())
            except Exception:
                sym0 = "T0"
            try:
                sym1 = str(erc1.functions.symbol().call())
            except Exception:
                sym1 = "T1"

            slot0 = pool.functions.slot0().call()
            sqrtP = int(slot0[0])
            p_t1_t0 = _sqrtPriceX96_to_price_t1_per_t0(sqrtP, dec0, dec1)

            reward = Web3.to_checksum_address(reward_token_addr)

            price_cake_usd: Optional[float] = None
            if reward == t0 and _is_usd_symbol(sym1):
                price_cake_usd = float(p_t1_t0)
            elif reward == t1 and _is_usd_symbol(sym0):
                price_cake_usd = (0.0 if p_t1_t0 == 0 else float(1.0 / p_t1_t0))

            if price_cake_usd is None:
                return None

            return float(pending_amount) * float(price_cake_usd)
        except Exception as e:
            print("exception", str(e))
            return None

    def compute(
        self,
        vault_address: str,
        dex: str = "",
        swap_pools: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        swap_pools = swap_pools or {}

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

        token0_addr = Web3.to_checksum_address(t0)
        token1_addr = Web3.to_checksum_address(t1)

        token_id = ad.current_token_id(vault_address) or vault.position_token_id()

        lower_tick = upper_tick = 0
        liquidity = 0

        fees0_raw = 0
        fees1_raw = 0

        has_gauge = bool(gauge and Web3.to_checksum_address(gauge) != ZERO_ADDR)
        staked = False
        position_location = "none"

        if token_id:
            nfpm = self._nfpm(nfpm_addr)

            pos = nfpm.functions.positions(int(token_id)).call()
            lower_tick = int(pos[5])
            upper_tick = int(pos[6])
            liquidity = int(pos[7])

            try:
                fees0_raw, fees1_raw = nfpm.functions.collect(
                    (int(token_id), Web3.to_checksum_address(vault_address), int(U128_MAX), int(U128_MAX))
                ).call()
            except Exception:
                fees0_raw, fees1_raw = 0, 0

            try:
                owner_of = nfpm.functions.ownerOf(int(token_id)).call()
                owner_of = Web3.to_checksum_address(owner_of)
                if has_gauge and owner_of == Web3.to_checksum_address(gauge):
                    staked = True
                    position_location = "gauge"
                else:
                    staked = False
                    position_location = "pool"
            except Exception:
                position_location = "pool"
        else:
            position_location = "none"

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

        current_block = _prices_from_tick(tick, dec0, dec1)
        lower_block = _prices_from_tick(lower_tick, dec0, dec1) if token_id else current_block
        upper_block = _prices_from_tick(upper_tick, dec0, dec1) if token_id else current_block

        out_of_range = False
        range_side = "inside"
        if token_id:
            out_of_range = tick < lower_tick or tick >= upper_tick
            if out_of_range:
                range_side = "below" if tick < lower_tick else "above"

        fees0_h = float(Decimal(int(fees0_raw)) / (Decimal(10) ** dec0))
        fees1_h = float(Decimal(int(fees1_raw)) / (Decimal(10) ** dec1))

        fees_usd: Optional[float] = None
        try:
            p_t1_t0 = float(current_block["p_t1_t0"])
            if _is_usd_symbol(sym1) or _is_stable_addr(token1_addr):
                fees_usd = float(fees0_h * p_t1_t0 + fees1_h)
            elif _is_usd_symbol(sym0) or _is_stable_addr(token0_addr):
                p_t0_t1 = float(current_block["p_t0_t1"])
                fees_usd = float(fees1_h * p_t0_t1 + fees0_h)
        except Exception:
            fees_usd = None

        # -------------------- Gauge rewards (REAL) --------------------
        gauge_rewards = {
            "reward_token": ZERO_ADDR,
            "reward_symbol": "N/A",
            "pending_raw": 0,
            "pending_amount": 0.0,
            "pending_usd_est": None,
        }
        gauge_reward_balances = {
            "token": ZERO_ADDR,
            "symbol": "N/A",
            "decimals": 18,
            "in_vault_raw": 0,
            "in_vault": 0.0,
        }

        if has_gauge and token_id:
            try:
                pending_raw = 0
                reward_token_addr = ZERO_ADDR
                reward_symbol = "REWARD"
                reward_dec = 18
                pending_h = 0.0
                pending_usd_est: Optional[float] = None

                # Pancake path: MasterChefV3 rewards in CAKE
                if (dex or "").strip().lower() == "pancake":
                    mc = self._pancake_masterchef(gauge)
                    pending_raw = int(mc.functions.pendingCake(int(token_id)).call())
                    reward_token_addr = Web3.to_checksum_address(mc.functions.CAKE().call())

                    erc = self._erc20(reward_token_addr)
                    try:
                        reward_symbol = str(erc.functions.symbol().call())
                    except Exception:
                        reward_symbol = "CAKE"
                    reward_dec = int(erc.functions.decimals().call())
                    pending_h = float(pending_raw) / (10 ** reward_dec)

                    # stable 1:1 quick path
                    if _is_usd_symbol(reward_symbol) or _is_stable_addr(reward_token_addr):
                        pending_usd_est = float(pending_h)
                    else:
                        # CAKE/USDC reference pool
                        pending_usd_est = self._pancake_reward_usd_est(
                            swap_pools=swap_pools,
                            pending_amount=pending_h,
                            reward_token_addr=reward_token_addr,
                        )

                # Generic gauge path
                else:
                    g = self._gauge_generic(gauge)
                    reward_token_addr = Web3.to_checksum_address(g.functions.rewardToken().call())
                    pending_raw = int(g.functions.earned(Web3.to_checksum_address(adapter_addr), int(token_id)).call())

                    erc = self._erc20(reward_token_addr)
                    try:
                        reward_symbol = str(erc.functions.symbol().call())
                    except Exception:
                        reward_symbol = "REWARD"
                    reward_dec = int(erc.functions.decimals().call())
                    pending_h = float(pending_raw) / (10 ** reward_dec)

                    if _is_usd_symbol(reward_symbol) or _is_stable_addr(reward_token_addr):
                        pending_usd_est = float(pending_h)

                gauge_rewards = {
                    "reward_token": Web3.to_checksum_address(reward_token_addr),
                    "reward_symbol": reward_symbol,
                    "pending_raw": int(pending_raw),
                    "pending_amount": float(pending_h),
                    "pending_usd_est": float(pending_usd_est) if pending_usd_est is not None else None,
                }

                # reward balances held by the vault itself
                try:
                    erc_r = self._erc20(reward_token_addr)
                    in_vault_raw = int(erc_r.functions.balanceOf(Web3.to_checksum_address(vault_address)).call())
                    in_vault = float(in_vault_raw) / (10 ** reward_dec)

                    gauge_reward_balances = {
                        "token": Web3.to_checksum_address(reward_token_addr),
                        "symbol": reward_symbol,
                        "decimals": int(reward_dec),
                        "in_vault_raw": int(in_vault_raw),
                        "in_vault": float(in_vault),
                    }
                except Exception:
                    # keep safe-zero block
                    pass

            except Exception:
                # keep safe-zero blocks
                pass

        out = VaultStatusOut(
            vault=Web3.to_checksum_address(vault_address),

            owner=owner,
            executor=executor,
            adapter=Web3.to_checksum_address(adapter_addr),
            dex_router=Web3.to_checksum_address(dex_router),
            fee_collector=Web3.to_checksum_address(fee_collector),
            strategy_id=int(strategy_id),

            pool=Web3.to_checksum_address(pool),
            nfpm=Web3.to_checksum_address(nfpm_addr),
            gauge=Web3.to_checksum_address(gauge) if has_gauge else ZERO_ADDR,

            token0=Erc20Meta(address=token0_addr, symbol=str(sym0), decimals=int(dec0)),
            token1=Erc20Meta(address=token1_addr, symbol=str(sym1), decimals=int(dec1)),

            position_token_id=int(token_id),
            liquidity=int(liquidity),
            lower_tick=int(lower_tick),
            upper_tick=int(upper_tick),
            tick_spacing=int(tick_spacing),

            tick=int(tick),
            sqrt_price_x96=int(sqrt_price_x96),
            prices=PricesOut(
                current=PriceBlock(**current_block),
                lower=PriceBlock(**lower_block),
                upper=PriceBlock(**upper_block),
            ),

            out_of_range=bool(out_of_range),
            range_side=str(range_side),

            holdings=HoldingsOut(
                vault_idle=HoldingsBlock(token0=float(vault_idle0), token1=float(vault_idle1)),
                in_position=HoldingsBlock(token0=float(inpos0), token1=float(inpos1)),
                totals=HoldingsBlock(token0=float(totals0), token1=float(totals1)),
                symbols={"token0": str(sym0), "token1": str(sym1)},
                addresses={"token0": token0_addr, "token1": token1_addr},
            ),

            fees_uncollected=FeesUncollectedOut(
                token0=float(fees0_h),
                token1=float(fees1_h),
                usd=(float(fees_usd) if fees_usd is not None else None),
            ),

            last_rebalance_ts=int(last_rebalance_ts),

            has_gauge=bool(has_gauge),
            staked=bool(staked),
            position_location=str(position_location),

            gauge_rewards=GaugeRewardsOut(**gauge_rewards),
            gauge_reward_balances=GaugeRewardBalancesOut(**gauge_reward_balances),
        )

        return out.model_dump()
