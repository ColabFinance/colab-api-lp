from __future__ import annotations

from typing import List

from pydantic import ConfigDict, Field

from core.domain.entities.base_entity import MongoEntity
from core.domain.enums.chain_registry_enums import ChainRegistryStatus


class ChainRegistryEntity(MongoEntity):
    """
    Mongo document used to store supported blockchain networks and their runtime configuration.
    """

    key: str = Field(..., description="Stable slug used as the registry key.")
    name: str
    chain_id: int

    status: ChainRegistryStatus = ChainRegistryStatus.ENABLED

    rpc_url: str
    explorer_url: str
    explorer_label: str

    native_symbol: str
    stables: List[str] = Field(default_factory=list)

    logo_url: str = ""

    model_config = ConfigDict(extra="allow", use_enum_values=True)