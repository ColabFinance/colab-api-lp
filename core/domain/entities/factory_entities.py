from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Optional


class FactoryStatus(StrEnum):
    """
    Status values stored in Mongo.

    Rules:
    - ACTIVE: this factory is currently used by the system.
    - ARCHIVED_CAN_CREATE_NEW: creation is allowed if the latest factory is in this status.
    """
    ACTIVE = "ACTIVE"
    ARCHIVED_CAN_CREATE_NEW = "ARCHIVED_CAN_CREATE_NEW"


@dataclass(frozen=True)
class StrategyFactoryEntity:
    chain: str
    address: str
    status: FactoryStatus
    created_at: datetime
    tx_hash: Optional[str] = None


@dataclass(frozen=True)
class VaultFactoryEntity:
    chain: str
    address: str
    status: FactoryStatus
    created_at: datetime
    tx_hash: Optional[str] = None
