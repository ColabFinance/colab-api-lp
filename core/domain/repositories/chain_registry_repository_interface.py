from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.entities.chain_registry_entity import ChainRegistryEntity


class ChainRegistryRepository(ABC):
    @abstractmethod
    def get_by_key(self, *, key: str) -> Optional[ChainRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def get_by_chain_id(self, *, chain_id: int) -> Optional[ChainRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def insert(self, entity: ChainRegistryEntity) -> None:
        raise NotImplementedError

    @abstractmethod
    def update(self, entity: ChainRegistryEntity) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self, *, limit: int = 200) -> Sequence[ChainRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def ensure_indexes(self) -> None:
        raise NotImplementedError