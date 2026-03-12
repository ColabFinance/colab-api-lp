
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.entities.dex_registry_entity import DexPoolEntity
from core.domain.enums.dex_registry_enums import DexRegistryStatus


class DexPoolRepository(ABC):
    @abstractmethod
    def get_by_pool(self, *, chain: str, dex: str, pool: str) -> Optional[DexPoolEntity]:
        raise NotImplementedError

    @abstractmethod
    def insert(self, entity: DexPoolEntity) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_by_dex(self, *, chain: str, dex: str, limit: int = 500) -> Sequence[DexPoolEntity]:
        raise NotImplementedError

    @abstractmethod
    def set_status(self, *, chain: str, dex: str, pool: str, status: DexRegistryStatus) -> int:
        raise NotImplementedError

    @abstractmethod
    def set_adapter(self, *, chain: str, dex: str, pool: str, adapter: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def ensure_indexes(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_by_pool_address(self, *, pool: str) -> Optional[DexPoolEntity]:
        raise NotImplementedError