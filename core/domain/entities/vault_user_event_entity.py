from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from .base_entity import MongoEntity


class VaultUserEventTransfer(BaseModel):
    token: str
    from_addr: str = Field(..., alias="from")
    to_addr: str = Field(..., alias="to")
    amount_raw: str

    amount_human: Optional[str] = None

    symbol: Optional[str] = None
    decimals: Optional[int] = None

    price_usd: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow", use_enum_values=True)


class VaultUserEventEntity(MongoEntity):
    """
    Collection: vault_user_events

    Idempotency key: (chain, tx_hash, event_type)
    """

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

    token_price_usd: Optional[str] = None

    to: Optional[str] = None
    transfers: Optional[List[VaultUserEventTransfer]] = None

    tx_hash: str
    block_number: Optional[int] = None

    model_config = ConfigDict(extra="allow", use_enum_values=True)
