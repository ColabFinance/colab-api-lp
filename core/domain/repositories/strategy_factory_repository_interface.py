from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.entities.factory_entities import StrategyFactoryEntity, FactoryStatus


class StrategyRepository(ABC):
    @abstractmethod
    def get_latest(self, *, chain: str) -> Optional[StrategyFactoryEntity]:
        raise NotImplementedError

    @abstractmethod
    def get_active(self, *, chain: str) -> Optional[StrategyFactoryEntity]:
        raise NotImplementedError

    @abstractmethod
    def insert(self, entity: StrategyFactoryEntity) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_all_status(self, *, chain: str, status: FactoryStatus) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_all(self, *, chain: str, limit: int = 50) -> Sequence[StrategyFactoryEntity]:
        raise NotImplementedError
