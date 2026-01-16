from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class AutoRebalancePancakeRequest(BaseModel):
    """
    Auto rebalance request.

    You can provide:
      - new_lower/new_upper (ticks), OR
      - lower_price/upper_price (UI prices) and api-lp will convert to ticks using pool metadata.
    """

    # ticks (optional if providing prices)
    new_lower: Optional[int] = Field(None, description="New lower tick (int24)")
    new_upper: Optional[int] = Field(None, description="New upper tick (int24)")

    # UI prices (optional if providing ticks)
    lower_price: Optional[float] = Field(None, description="UI lower price (human)")
    upper_price: Optional[float] = Field(None, description="UI upper price (human)")

    # fee can be inferred from pool if None
    fee: Optional[int] = Field(None, ge=0, le=1_000_000, description="Pool fee tier (uint24). If None, infer from pool.")

    token_in: str = Field(..., description="TokenIn address")
    token_out: str = Field(..., description="TokenOut address")

    swap_amount_in: int = Field(0, ge=0, description="Exact input amount in raw units (uint256). 0 = no swap")
    swap_amount_out_min: int = Field(0, ge=0, description="Minimum output amount in raw units (uint256)")
    sqrt_price_limit_x96: int = Field(0, ge=0, description="Optional sqrtPriceLimitX96 (uint160). Usually 0")

    gas_strategy: str = Field(default="buffered", description="default|buffered|aggressive")
    meta: Optional[Dict[str, Any]] = None
