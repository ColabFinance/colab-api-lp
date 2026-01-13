# adapters/external/database/vault_events_repository.py
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.collection import Collection
from pymongo.database import Database
from .helper_repo import sanitize_for_mongo

from adapters.external.database.mongo_client import get_mongo_db
from core.domain.entities.vault_event_entity import VaultEvent
from core.domain.repositories.vault_events_repository_interface import VaultEventsRepositoryInterface


class VaultEventsRepository(VaultEventsRepositoryInterface):
    """
    Repository responsible for storing and querying vault-related events.

    Each event is stored as a separate document in the 'vault_events' collection
    and mapped to a `VaultEvent` entity.
    """

    COLLECTION_NAME = "vault_events"

    def __init__(self, db: Optional[Database] = None) -> None:
        """
        Initialize the repository.

        Args:
            db: Optional MongoDB database instance. If omitted, the default
                vaults database is obtained via get_mongo_db().
        """
        self._db: Database = db or get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]

    @property
    def collection(self) -> Collection:
        """
        Return the underlying MongoDB collection for administrative access.
        """
        return self._collection

    def ensure_indexes(self) -> None:
        """
        Ensure indexes that make querying recent events efficient.

        - Compound index (dex, alias, kind, ts desc) for time-ordered queries.
        """
        self._collection.create_index(
            [("dex", 1), ("alias", 1), ("kind", 1), ("ts", -1)],
            name="ix_vault_events_dex_alias_kind_ts_desc",
        )

    def append_event(self, dex: str, alias: str, kind: str, payload: Dict[str, Any]) -> None:
        """
        Insert a new event document for a given vault.

        Args:
            dex: DEX identifier.
            alias: Vault alias.
            kind: Event kind (e.g. 'exec', 'collect', 'deposit', 'error', 'rewards_collect').
            payload: Arbitrary JSON-serializable dictionary with event data.
        """
        now_s = int(time.time())
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        event = VaultEvent(
            dex=dex,
            alias=alias,
            kind=kind,
            ts=now_s,
            ts_iso=now_iso,
            payload=payload or {},
        )
        doc = event.to_mongo()
        doc = sanitize_for_mongo(doc)
        self._collection.insert_one(doc)

    def get_recent_events(
        self,
        dex: str,
        alias: str,
        kind: Optional[str] = None,
        limit: int = 2000,
    ) -> List[VaultEvent]:
        """
        Fetch the most recent events for a given vault.

        Args:
            dex: DEX identifier.
            alias: Vault alias.
            kind: Optional filter for the event kind. If omitted, all kinds are returned.
            limit: Maximum number of events to return (ordered from newest to oldest).

        Returns:
            A list of `VaultEvent` entities.
        """
        query: Dict[str, Any] = {"dex": dex, "alias": alias}
        if kind is not None:
            query["kind"] = kind

        cursor = (
            self._collection
            .find(query)
            .sort("ts", -1)
            .limit(int(limit))
        )
        return [VaultEvent.from_mongo(doc) for doc in cursor]
