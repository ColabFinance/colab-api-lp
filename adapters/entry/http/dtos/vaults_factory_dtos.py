from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class FactoryConfigOut(BaseModel):
    executor: str
    feeCollector: str
    defaultCooldownSec: int
    defaultMaxSlippageBps: int
    defaultAllowSwap: bool


class CreateClientVaultRequest(BaseModel):
    strategy_id: int = Field(..., ge=1)
    owner_override: Optional[str] = Field(
        default=None,
        description="Se quiser criar vault para outro owner. Se None, usa msg.sender do signer (backend PK).",
    )
    gas_strategy: str = Field(default="buffered", description="default|buffered|aggressive")


class SetExecutorRequest(BaseModel):
    new_executor: str
    gas_strategy: str = Field(default="buffered")


class SetFeeCollectorRequest(BaseModel):
    new_collector: str
    gas_strategy: str = Field(default="buffered")


class SetDefaultsRequest(BaseModel):
    cooldown_sec: int = Field(..., ge=0)
    max_slippage_bps: int = Field(..., ge=0, le=10_000)
    allow_swap: bool
    gas_strategy: str = Field(default="buffered")


class TxRunResponse(BaseModel):
    tx_hash: str
    broadcasted: bool
    receipt: Optional[Dict[str, Any]] = None
    status: Optional[int] = None
    gas_limit_used: Optional[int] = None
    gas_price_wei: Optional[int] = None
    gas_budget_check: Optional[Dict[str, Any]] = None
