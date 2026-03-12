from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.entities.dex_registry_entity import DexRegistryEntity
from core.domain.enums.dex_registry_enums import DexRegistryStatus


class DexRegistryRepository(ABC):
    @abstractmethod
    def ensure_indexes(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_by_key(self, *, chain: str, dex: str) -> Optional[DexRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def insert(self, entity: DexRegistryEntity) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_by_key(
        self,
        *,
        chain: str,
        dex: str,
        dex_router: str,
        status: DexRegistryStatus,
    ) -> Optional[DexRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def list_all(self, *, chain: str, limit: int = 200) -> Sequence[DexRegistryEntity]:
        raise NotImplementedError