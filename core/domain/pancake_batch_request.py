from typing import Optional
from pydantic import BaseModel

class PancakeBatchRequest(BaseModel):
    token_in: str
    token_out: str
    amount_in: Optional[float] = None          # human in token_in
    amount_in_usd: Optional[float] = None      # alternative in USD (if supported)
    fee: Optional[int] = None                  # optional; we infer from pool if not set
    sqrt_price_limit_x96: Optional[int] = None
    slippage_bps: int = 50
    max_budget_usd: Optional[float] = None
    pool_override: Optional[str] = None

    # range: same pattern as /open
    lower_tick: Optional[int] = None
    upper_tick: Optional[int] = None
    lower_price: Optional[float] = None
    upper_price: Optional[float] = None
