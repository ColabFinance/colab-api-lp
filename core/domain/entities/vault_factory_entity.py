from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict

from core.domain.enums.factory_enums import FactoryStatus

from .base_entity import MongoEntity


class VaultFactoryEntity(MongoEntity):
    """
    Mongo document (collection: vault_factories).
    Represents an on-chain VaultFactory record.
    """

    chain: str
    address: str
    status: FactoryStatus
    tx_hash: Optional[str] = None

    owner: Optional[str] = None
    strategy_registry: Optional[str] = None
    executor: Optional[str] = None
    fee_collector: Optional[str] = None

    default_cooldown_sec: Optional[int] = None
    default_max_slippage_bps: Optional[int] = None
    default_allow_swap: Optional[bool] = None

    model_config = ConfigDict(extra="allow", use_enum_values=True)