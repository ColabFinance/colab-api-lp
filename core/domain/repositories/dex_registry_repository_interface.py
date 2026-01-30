from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.entities.dex_registry_entity import DexRegistryEntity


class DexRegistryRepository(ABC):
    @abstractmethod
    def get_by_key(self, *, chain: str, dex: str) -> Optional[DexRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def insert(self, entity: DexRegistryEntity) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self, *, chain: str, limit: int = 200) -> Sequence[DexRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def ensure_indexes(self) -> None:
        raise NotImplementedError
