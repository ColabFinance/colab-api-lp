from typing import Any, Dict, Optional, Literal
from pydantic import BaseModel


class TokenMetaOut(BaseModel):
    address: str
    symbol: str
    decimals: int


class PricesBlockOut(BaseModel):
    tick: int
    p_t1_t0: float
    p_t0_t1: float


class PricesPanelOut(BaseModel):
    current: PricesBlockOut
    lower: PricesBlockOut
    upper: PricesBlockOut


class HoldingsSideOut(BaseModel):
    token0: float
    token1: float
    total_usd: Optional[float] = None


class HoldingsOut(BaseModel):
    vault_idle: HoldingsSideOut
    in_position: HoldingsSideOut
    totals: HoldingsSideOut

    # extra fields required by api-signals
    symbols: Dict[str, str]          # {"token0": "WETH", "token1": "USDC"}
    addresses: Dict[str, str]        # {"token0": "0x..", "token1": "0x.."}


class FeesUncollectedOut(BaseModel):
    token0: float
    token1: float
    usd: Optional[float] = None      # convenient aggregation for api-signals


class GaugeRewardsOut(BaseModel):
    reward_token: str
    reward_symbol: str
    pending_raw: int
    pending_amount: float
    pending_usd_est: Optional[float] = None


class GaugeRewardBalancesOut(BaseModel):
    token: str
    symbol: str
    decimals: int
    in_vault_raw: int
    in_vault: float


class VaultStatusOut(BaseModel):
    # identity
    vault: str

    # wiring (vault)
    owner: str
    executor: str
    adapter: str
    dex_router: str
    fee_collector: str
    strategy_id: int

    # wiring (adapter)
    pool: str
    nfpm: str
    gauge: str

    # tokens
    token0: TokenMetaOut
    token1: TokenMetaOut

    # position
    position_token_id: int
    liquidity: int
    lower_tick: int
    upper_tick: int
    tick_spacing: int

    # pool price
    tick: int
    sqrt_price_x96: int
    prices: PricesPanelOut

    # range flags
    out_of_range: bool
    range_side: Literal["inside", "below", "above"]

    # inventory
    holdings: HoldingsOut

    # fee preview (callStatic-style via NFPM.collect .call())
    fees_uncollected: FeesUncollectedOut

    # vault state
    last_rebalance_ts: int

    # extra for api-signals
    has_gauge: bool
    staked: bool
    position_location: Literal["none", "pool", "gauge"]

    gauge_rewards: GaugeRewardsOut
    gauge_reward_balances: GaugeRewardBalancesOut
