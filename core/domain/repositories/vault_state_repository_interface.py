from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from core.domain.entities.vault_state_entity import VaultStateDocument


class VaultStateRepositoryInterface(Protocol):
    """
    Abstraction for current vault state persistence.
    """

    def ensure_indexes(self) -> None:
        ...

    def get_state(self, dex: str, alias: str) -> Dict[str, Any]:
        ...

    def upsert_state(self, dex: str, alias: str, state: Dict[str, Any]) -> None:
        ...

    def patch_state(self, dex: str, alias: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        ...

    # opcional, mas útil para quem quiser trabalhar com a entidade diretamente
    def _get_state_doc(self, dex: str, alias: str) -> Optional[VaultStateDocument]:
        ...

    def _upsert_state_doc(self, dex: str, alias: str, state: Dict[str, Any]) -> VaultStateDocument:
        ...
