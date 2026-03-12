from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict

from core.domain.enums.factory_enums import FactoryStatus

from .base_entity import MongoEntity


class StrategyRegistryEntity(MongoEntity):
    """
    Mongo document (collection: strategy_factories).
    Represents an on-chain StrategyRegistry record.
    """

    chain: str
    address: str
    status: FactoryStatus
    tx_hash: Optional[str] = None
    owner: Optional[str] = None

    model_config = ConfigDict(extra="allow", use_enum_values=True)