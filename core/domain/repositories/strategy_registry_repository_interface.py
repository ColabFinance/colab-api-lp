from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.entities.strategy_registry_entity import StrategyRegistryEntity
from core.domain.enums.factory_enums import FactoryStatus


class StrategyRepository(ABC):
    @abstractmethod
    def get_latest(self, *, chain: str) -> Optional[StrategyRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def get_active(self, *, chain: str) -> Optional[StrategyRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def insert(self, entity: StrategyRegistryEntity) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_all_status(self, *, chain: str, status: FactoryStatus) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_all(self, *, chain: str, limit: int = 50) -> Sequence[StrategyRegistryEntity]:
        raise NotImplementedError
