from typing import Any, Dict, Optional
from pydantic import BaseModel


class TxGasOut(BaseModel):
    limit: int
    used: int
    price_wei: int
    effective_price_wei: int
    cost_eth: Optional[float] = None
    cost_usd: Optional[float] = None


class TxBudgetOut(BaseModel):
    max_gas_usd: Optional[float] = None
    eth_usd_hint: Optional[float] = None
    usd_estimated_upper_bound: Optional[float] = None
    budget_exceeded: bool


class TxResponse(BaseModel):
    tx_hash: str
    broadcasted: bool
    status: Optional[int] = None
    receipt: Optional[Dict[str, Any]] = None
    gas: TxGasOut
    budget: TxBudgetOut
    result: Dict[str, Any]
    ts: str
