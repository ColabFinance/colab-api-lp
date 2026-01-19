from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import ConfigDict

from .base_entity import MongoEntity


class FactoryStatus(StrEnum):
    """
    Status values stored in Mongo.

    Rules:
    - ACTIVE: this factory is currently used by the system.
    - ARCHIVED_CAN_CREATE_NEW: creation is allowed if the latest factory is in this status.
    """

    ACTIVE = "ACTIVE"
    ARCHIVED_CAN_CREATE_NEW = "ARCHIVED_CAN_CREATE_NEW"


class StrategyFactoryEntity(MongoEntity):
    """
    Mongo document (collection: strategy_factories).
    Represents an on-chain StrategyRegistry factory record.
    """

    chain: str
    address: str
    status: FactoryStatus
    tx_hash: Optional[str] = None

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class VaultFactoryEntity(MongoEntity):
    """
    Mongo document (collection: vault_factories).
    Represents an on-chain VaultFactory record.
    """

    chain: str
    address: str
    status: FactoryStatus
    tx_hash: Optional[str] = None

    model_config = ConfigDict(extra="allow", use_enum_values=True)
