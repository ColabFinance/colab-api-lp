from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from core.domain.entities.vault_event_entity import VaultEvent


class VaultEventsRepositoryInterface(Protocol):
    """
    Abstraction for historical vault events persistence.
    """

    def ensure_indexes(self) -> None:
        ...

    def append_event(self, dex: str, alias: str, kind: str, payload: Dict[str, Any]) -> None:
        ...

    def get_recent_events(
        self,
        dex: str,
        alias: str,
        kind: Optional[str] = None,
        limit: int = 2000,
    ) -> List[VaultEvent]:
        ...
