from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

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
    def find_by_address(self, address: str) -> Optional[VaultRegistryEntity]:
        raise NotImplementedError

    @abstractmethod
    def count_alias_prefix(self, *, chain: str, dex: str, owner_prefix: str, par_token: str) -> int:
        """
        Used to generate the incremental alias number.
        """
        raise NotImplementedError

    @abstractmethod
    def list_by_owner(
        self,
        *,
        owner: str,
        chain: Optional[str] = None,
        dex: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[VaultRegistryEntity]:
        """
        List vault registry docs from Mongo by owner (and optional chain/dex).
        """
        raise NotImplementedError

    @abstractmethod
    def update_fields(self, *, address: str, set_fields: Dict[str, Any]) -> VaultRegistryEntity:
        """
        Apply $set updates to a vault doc (by address) and return the updated entity.
        """
        raise NotImplementedError
