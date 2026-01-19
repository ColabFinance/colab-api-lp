from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import ConfigDict

from core.domain.enums.factory_enums import FactoryStatus

from .base_entity import MongoEntity


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
