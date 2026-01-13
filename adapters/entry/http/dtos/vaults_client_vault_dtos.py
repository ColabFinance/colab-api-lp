from typing import Any, Dict, Optional, Literal
from pydantic import BaseModel, Field

class TxRunResponse(BaseModel):
    tx_hash: str
    broadcasted: bool
    receipt: Optional[Dict[str, Any]] = None
    status: Optional[int] = None
    gas_limit_used: Optional[int] = None
    gas_price_wei: Optional[int] = None
    gas_budget_check: Optional[Dict[str, Any]] = None


# ----------------------------
# Vault status (read-only)
# ----------------------------

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


class HoldingsOut(BaseModel):
    vault_idle: HoldingsSideOut
    in_position: HoldingsSideOut
    totals: HoldingsSideOut


class FeesUncollectedOut(BaseModel):
    token0: float
    token1: float


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



class AutoRebalancePancakeIn(BaseModel):
    newLowerTick: int = Field(...)
    newUpperTick: int = Field(...)
    fee: int = Field(..., description="uint24")
    tokenIn: str = Field(...)
    tokenOut: str = Field(...)
    swapAmountIn: int = Field(..., description="uint256")
    swapAmountOutMin: int = Field(..., description="uint256")
    sqrtPriceLimitX96: int = Field(..., description="uint160")
    gas_strategy: str = Field(default="buffered")
    
    
class CreateClientVaultRequest(BaseModel):
    strategy_id: int = Field(..., ge=1)
    owner_override: Optional[str] = Field(
        default=None,
        description="Se quiser criar vault para outro owner. Se None, usa msg.sender do signer (backend PK).",
    )
    gas_strategy: str = Field(default="buffered", description="default|buffered|aggressive")
