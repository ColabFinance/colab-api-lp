from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict

from core.domain.entities.base_entity import MongoEntity
from core.domain.enums.factory_enums import FactoryStatus


class VaultFeeBufferEntity(MongoEntity):
    """
    Mongo document (collection: vault_fee_buffers).

    Represents a VaultFeeBuffer deployment record.
    """

    chain: str
    address: str
    status: FactoryStatus
    tx_hash: Optional[str] = None

    owner: str

    model_config = ConfigDict(extra="allow", use_enum_values=True)
