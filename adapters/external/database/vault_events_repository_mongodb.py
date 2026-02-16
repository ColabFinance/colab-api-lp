# vault_events_repository_mongodb.py

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo
from adapters.external.database.mongo_client import get_mongo_db
from core.domain.entities.vault_event_entity import VaultEvent
from core.domain.repositories.vault_events_repository_interface import VaultEventsRepositoryInterface
from core.services.normalize import _norm_lower


class VaultEventsRepository(VaultEventsRepositoryInterface):
    """
    Repository responsible for storing and querying vault-related events.

    Collection: vault_events
    """

    COLLECTION_NAME = "vault_events"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db or get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("dex", 1), ("alias", 1), ("kind", 1), ("ts", -1)],
            name="ix_vault_events_dex_alias_kind_ts_desc",
        )

    def append_event(self, dex: str, alias: str, kind: str, payload: Dict[str, Any]) -> None:
        now_s = int(time.time())
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        event = VaultEvent(
            dex=_norm_lower(dex),
            alias=_norm_lower(alias),
            kind=_norm_lower(kind),
            ts=now_s,
            ts_iso=now_iso,
            payload=payload or {},
        )

        event.created_at = event.now_ms()
        event.created_at_iso = event.now_iso()
        event.updated_at = event.created_at
        event.updated_at_iso = event.created_at_iso

        doc = sanitize_for_mongo(event.to_mongo())
        self._collection.insert_one(doc)

    def get_recent_events(
        self,
        dex: str,
        alias: str,
        kind: Optional[str] = None,
        limit: int = 2000,
    ) -> List[VaultEvent]:
        query: Dict[str, Any] = {"dex": _norm_lower(dex), "alias": _norm_lower(alias)}
        if kind is not None:
            query["kind"] = _norm_lower(kind)

        cursor = self._collection.find(query).sort("ts", -1).limit(int(limit))
        out: List[VaultEvent] = []
        for doc in cursor:
            ev = VaultEvent.from_mongo(doc)
            if ev:
                out.append(ev)
        return out
