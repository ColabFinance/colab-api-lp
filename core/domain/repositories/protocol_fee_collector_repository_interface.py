from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.entities.protocol_fee_collector_entity import ProtocolFeeCollectorEntity
from core.domain.enums.factory_enums import FactoryStatus


class ProtocolFeeCollectorRepository(ABC):
    """
    Repository contract for ProtocolFeeCollector deployments.
    """

    @abstractmethod
    def get_latest(self, *, chain: str) -> Optional[ProtocolFeeCollectorEntity]:
        raise NotImplementedError

    @abstractmethod
    def get_active(self, *, chain: str) -> Optional[ProtocolFeeCollectorEntity]:
        raise NotImplementedError

    @abstractmethod
    def insert(self, entity: ProtocolFeeCollectorEntity) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_all_status(self, *, chain: str, status: FactoryStatus) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_all(self, *, chain: str, limit: int = 50) -> Sequence[ProtocolFeeCollectorEntity]:
        raise NotImplementedError
