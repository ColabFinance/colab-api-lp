from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import AliasChoices, BaseModel, Field


class VaultUserEventTransfer(BaseModel):
    token: str
    from_addr: str = Field(
        ...,
        validation_alias=AliasChoices("from", "from_addr"),
        serialization_alias="from",
    )
    to_addr: str = Field(
        ...,
        validation_alias=AliasChoices("to", "to_addr"),
        serialization_alias="to",
    )
    amount_raw: str

    symbol: Optional[str] = None
    decimals: Optional[int] = None


class VaultUserEventDepositIn(BaseModel):
    chain: str = Field(..., description="ex: base|bnb")
    dex: Optional[str] = Field(None, description="optional (for UI grouping)")
    owner: Optional[str] = Field(None, description="user wallet (actor)")

    token: str = Field(..., description="ERC20 token address deposited")
    amount_human: Optional[str] = Field(None, description="human amount (optional)")
    amount_raw: Optional[str] = Field(None, description="raw amount (optional)")
    decimals: Optional[int] = Field(None, description="token decimals (optional)")

    tx_hash: str
    receipt: Optional[Dict[str, Any]] = None

    # optional hints (helps parsing logs)
    from_addr: Optional[str] = Field(None, description="expected sender (actor)")
    to_addr: Optional[str] = Field(None, description="expected receiver (vault)")


class VaultUserEventWithdrawIn(BaseModel):
    chain: str = Field(..., description="ex: base|bnb")
    dex: Optional[str] = Field(None, description="optional (for UI grouping)")
    owner: Optional[str] = Field(None, description="user wallet (actor)")

    to: str = Field(..., description="withdraw destination address")

    tx_hash: str
    receipt: Optional[Dict[str, Any]] = None

    # Optional: backend will try to parse ERC20 Transfer logs and aggregate amounts for these tokens
    token_addresses: List[str] = Field(default_factory=list, description="tokens to track in logs (token0/token1/reward)")


class VaultUserEventOut(BaseModel):
    id: str

    vault: str
    alias: Optional[str] = None

    chain: str
    dex: Optional[str] = None

    event_type: str  # deposit | withdraw
    owner: Optional[str] = None

    token: Optional[str] = None
    amount_human: Optional[str] = None
    amount_raw: Optional[str] = None
    decimals: Optional[int] = None

    to: Optional[str] = None
    transfers: Optional[List[VaultUserEventTransfer]] = None

    tx_hash: str
    block_number: Optional[int] = None
    ts_ms: int
    ts_iso: str


class VaultUserEventsListOut(BaseModel):
    ok: bool = True
    message: str = "ok"
    data: List[VaultUserEventOut] = Field(default_factory=list)
    total: Optional[int] = None
