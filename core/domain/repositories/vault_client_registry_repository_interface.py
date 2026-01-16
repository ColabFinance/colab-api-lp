# core/domain/repositories/vault_registry_repository_interface.py

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from core.domain.entities.vault_client_registry_entity import VaultRegistryEntity


class VaultRegistryRepositoryInterface(ABC):
    @abstractmethod
    def ensure_indexes(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def insert(self, entity: VaultRegistryEntity) -> VaultRegistryEntity:
        raise NotImplementedError

    @abstractmethod
    def find_by_alias(self, alias: str) -> Optional[VaultRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def count_alias_prefix(self, *, chain: str, dex: str, owner_prefix: str, par_token: str) -> int:
        """
        Used to generate the incremental alias number.
        """
        raise NotImplementedError
