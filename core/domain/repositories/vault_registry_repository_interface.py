from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Tuple

from core.domain.entities.vault_registry_entity import VaultRegistryEntry


class VaultRegistryRepositoryInterface(Protocol):
    """
    Abstraction for vault registry persistence.

    Implementations live in the adapters layer (e.g. MongoDB).
    """

    def list_by_dex(self, dex: str) -> List[VaultRegistryEntry]:
        ...

    def get_active_for_dex(self, dex: str) -> Optional[VaultRegistryEntry]:
        ...

    def get_by_dex_alias(self, dex: str, alias: str) -> Optional[VaultRegistryEntry]:
        ...

    def create_vault(self, dex: str, alias: str, config: Dict[str, Any]) -> VaultRegistryEntry:
        ...

    def set_active(self, dex: str, alias: str) -> None:
        ...

    def set_pool(self, dex: str, alias: str, pool_addr: str) -> None:
        ...

    def find_any_by_alias(self, alias: str) -> Tuple[Optional[str], Optional[VaultRegistryEntry]]:
        ...
