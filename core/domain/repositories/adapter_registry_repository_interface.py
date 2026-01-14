from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.entities.adapter_registry_entity import AdapterRegistryEntity


class AdapterRegistryRepository(ABC):
    @abstractmethod
    def ensure_indexes(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_by_dex_pool(self, *, chain: str, dex: str, pool: str) -> Optional[AdapterRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def get_by_address(self, *, address: str) -> Optional[AdapterRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def insert(self, entity: AdapterRegistryEntity) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self, *, chain: str, limit: int = 100) -> Sequence[AdapterRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def list_active(self, *, chain: str, limit: int = 50) -> Sequence[AdapterRegistryEntity]:
        raise NotImplementedError