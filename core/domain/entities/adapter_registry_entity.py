from __future__ import annotations

from enum import Enum

from pydantic import ConfigDict

from .base_entity import MongoEntity


class AdapterStatus(str, Enum):
    """
    Adapter record status stored in MongoDB.

    ACTIVE: can be selected/used by services that resolve adapters.
    INACTIVE: kept for history but should not be used by default.
    """

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AdapterRegistryEntity(MongoEntity):
    """
    Mongo document (collection: adapter_registry).

    Fields:
    - chain: chain identifier (e.g. "base", "bnb", ...)
    - address: deployed adapter contract address
    - dex: identifier (e.g. "pancake_v3")
    - pool/nfpm/gauge: constructor wiring addresses
    - token0/token1: underlying tokens for the pool
    - pool_name: human label (e.g. "WETH/USDC")
    - fee_bps: string representation (e.g. "100", "300")
    - status: ACTIVE|INACTIVE
    - tx_hash/created_by: optional audit metadata
    - created_at/created_at_iso/updated_at/updated_at_iso: inherited timestamps
    """

    chain: str
    address: str

    dex: str

    pool: str
    nfpm: str
    gauge: str

    token0: str
    token1: str
    pool_name: str
    fee_bps: str
    status: AdapterStatus

    tx_hash: str | None = None
    created_by: str | None = None

    model_config = ConfigDict(extra="allow", use_enum_values=True)
