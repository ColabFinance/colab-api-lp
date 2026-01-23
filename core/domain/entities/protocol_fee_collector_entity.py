from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict

from core.domain.enums.factory_enums import FactoryStatus
from core.domain.entities.base_entity import MongoEntity


class ProtocolFeeCollectorEntity(MongoEntity):
    """
    Mongo document (collection: protocol_fee_collectors).

    Represents a ProtocolFeeCollector deployment record.
    The contract stores treasury/protocolFeeBps on-chain; we persist them for admin visibility.
    """

    chain: str
    address: str
    status: FactoryStatus
    tx_hash: Optional[str] = None

    treasury: str
    protocol_fee_bps: int

    model_config = ConfigDict(extra="allow", use_enum_values=True)
