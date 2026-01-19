from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field


class Erc20Meta(BaseModel):
    address: str
    symbol: str
    decimals: int


class PoolMeta(BaseModel):
    token0: str
    token1: str
    dec0: int
    dec1: int
    sym0: str
    sym1: str
    spacing: int
    fee: int


class RangeDebug(BaseModel):
    sym0: str
    sym1: str
    dec0: int
    dec1: int
    spacing: int


class RangeUsed(BaseModel):
    lower_tick: int
    upper_tick: int


class AutoRebalancePancakeParams(BaseModel):
    new_lower: int = Field(..., alias="newLower")
    new_upper: int = Field(..., alias="newUpper")
    fee: int
    token_in: str = Field(..., alias="tokenIn")
    token_out: str = Field(..., alias="tokenOut")
    swap_amount_in: int = Field(..., alias="swapAmountIn")
    swap_amount_out_min: int = Field(..., alias="swapAmountOutMin")
    sqrt_price_limit_x96: int = Field(0, alias="sqrtPriceLimitX96")

    def to_abi_dict(self) -> Dict[str, Any]:
        # MUST match solidity struct field names
        return {
            "newLower": int(self.new_lower),
            "newUpper": int(self.new_upper),
            "fee": int(self.fee),
            "tokenIn": self.token_in,
            "tokenOut": self.token_out,
            "swapAmountIn": int(self.swap_amount_in),
            "swapAmountOutMin": int(self.swap_amount_out_min),
            "sqrtPriceLimitX96": int(self.sqrt_price_limit_x96 or 0),
        }

class VaultFactoryConfig(BaseModel):
    executor: str
    fee_collector: str
    default_cooldown_sec: int
    default_max_slippage_bps: int
    default_allow_swap: bool


class PriceBlock(BaseModel):
    tick: int
    p_t1_t0: float
    p_t0_t1: float


class PricesOut(BaseModel):
    current: PriceBlock
    lower: PriceBlock
    upper: PriceBlock


class HoldingsBlock(BaseModel):
    token0: float
    token1: float


class HoldingsOut(BaseModel):
    vault_idle: HoldingsBlock
    in_position: HoldingsBlock
    totals: HoldingsBlock
    symbols: Dict[str, str]
    addresses: Dict[str, str]


class FeesUncollectedOut(BaseModel):
    token0: float
    token1: float
    usd: Optional[float]


class GaugeRewardsOut(BaseModel):
    reward_token: str
    reward_symbol: str
    pending_raw: int
    pending_amount: float
    pending_usd_est: Optional[float]


class GaugeRewardBalancesOut(BaseModel):
    token: str
    symbol: str
    decimals: int
    in_vault_raw: int
    in_vault: float


class VaultStatusOut(BaseModel):
    vault: str
    owner: str
    executor: str
    adapter: str
    dex_router: str
    fee_collector: str
    strategy_id: int

    pool: str
    nfpm: str
    gauge: str

    token0: Erc20Meta
    token1: Erc20Meta

    position_token_id: int
    liquidity: int
    lower_tick: int
    upper_tick: int
    tick_spacing: int

    tick: int
    sqrt_price_x96: int
    prices: PricesOut

    out_of_range: bool
    range_side: str

    holdings: HoldingsOut
    fees_uncollected: FeesUncollectedOut

    last_rebalance_ts: int

    has_gauge: bool
    staked: bool
    position_location: str

    gauge_rewards: GaugeRewardsOut
    gauge_reward_balances: GaugeRewardBalancesOut
