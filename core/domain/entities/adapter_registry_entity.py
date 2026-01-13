from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AdapterStatus(str, Enum):
    """
    Adapter record status stored in MongoDB.

    ACTIVE: can be selected/used by services that resolve adapters.
    INACTIVE: kept for history but should not be used by default.
    """
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


@dataclass(frozen=True)
class AdapterRegistryEntity:
    """
    Mongo document (collection: adapter_registry)

    On-chain deployment:
      - address: deployed adapter contract address (result of tx deploy)

    Contract-required wiring (PancakeV3Adapter constructor):
      - pool: address
      - nfpm: address
      - gauge: address (may be zero)

    Mongo-only metadata (not part of the contract state):
      - dex: identifier (e.g. "pancake_v3")
      - token0/token1: underlying tokens for the pool
      - pool_name: human label (e.g. "WETH/USDC")
      - fee_bps: string representation (e.g. "100", "300")
      - status: ACTIVE|INACTIVE

    Security:
      - addresses must be normalized (checksum or lower) consistently.
      - uniqueness is enforced at DB-level via a unique compound index.
    """

    # On-chain deployed contract address
    address: str

    # Identity / lookup
    dex: str

    # Contract constructor params
    pool: str
    nfpm: str
    gauge: str  # may be zero address

    # Mongo metadata
    token0: str
    token1: str
    pool_name: str
    fee_bps: str
    status: AdapterStatus

    # Audit
    created_at: datetime
    tx_hash: str | None = None
    created_by: str | None = None
