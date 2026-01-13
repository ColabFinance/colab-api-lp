from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.entities.factory_entities import VaultFactoryEntity, FactoryStatus


class VaultFactoryRepository(ABC):
    @abstractmethod
    def get_latest(self) -> Optional[VaultFactoryEntity]:
        raise NotImplementedError

    @abstractmethod
    def get_active(self) -> Optional[VaultFactoryEntity]:
        raise NotImplementedError

    @abstractmethod
    def insert(self, entity: VaultFactoryEntity) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_all_status(self, *, status: FactoryStatus) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_all(self, *, limit: int = 50) -> Sequence[VaultFactoryEntity]:
        raise NotImplementedError
