# adapters/external/database/vault_state_repository.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.mongo_client import get_mongo_db
from core.domain.entities.vault_state_entity import VaultStateDocument


class VaultStateRepository:
    """
    Repository responsible for storing and retrieving the *current* vault state.

    One document per (dex, alias) combination is stored in the 'vault_state'
    collection and mapped to a `VaultStateDocument` entity. The public API
    still exposes the inner `state` dictionary for convenience.
    """

    COLLECTION_NAME = "vault_state"

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
        Return the underlying MongoDB collection.

        This is mainly intended for administrative tasks such as index creation.
        """
        return self._collection

    def ensure_indexes(self) -> None:
        """
        Ensure that the required indexes exist on the collection.

        - Unique composite index on (dex, alias) so each vault has a single state document.
        """
        self._collection.create_index(
            [("dex", 1), ("alias", 1)],
            unique=True,
            name="ux_vault_state_dex_alias",
        )

    # ---------- internal helpers for entities ----------

    def _get_state_doc(self, dex: str, alias: str) -> Optional[VaultStateDocument]:
        """
        Fetch the full VaultStateDocument entity for a given (dex, alias).

        Returns:
            A `VaultStateDocument` or None if no document exists.
        """
        doc = self._collection.find_one({"dex": dex, "alias": alias})
        return VaultStateDocument.from_mongo(doc) if doc else None

    def _upsert_state_doc(self, dex: str, alias: str, state: Dict[str, Any]) -> VaultStateDocument:
        """
        Upsert the underlying VaultStateDocument entity for (dex, alias).
        """
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        existing_doc = self._collection.find_one({"dex": dex, "alias": alias})
        if existing_doc:
            entity = VaultStateDocument.from_mongo(existing_doc)
            entity.state = state
            entity.updated_at = now
            self._collection.update_one(
                {"_id": entity.id},
                {"$set": {"state": entity.state, "updated_at": entity.updated_at}},
            )
            return entity

        entity = VaultStateDocument(
            dex=dex,
            alias=alias,
            state=state,
            created_at=now,
            updated_at=now,
        )
        mongo_doc = entity.to_mongo()
        result = self._collection.insert_one(mongo_doc)
        entity.id = result.inserted_id
        return entity

    # ---------- public API (dict-based state) ----------

    def get_state(self, dex: str, alias: str) -> Dict[str, Any]:
        """
        Fetch the current state payload for a given (dex, alias).

        Args:
            dex: DEX identifier (e.g. 'uniswap', 'aerodrome', 'pancake').
            alias: Logical vault alias.

        Returns:
            A dictionary containing the 'state' payload, or an empty dict if no state exists.
        """
        entity = self._get_state_doc(dex, alias)
        if entity is None:
            return {}
        return entity.state or {}

    def upsert_state(self, dex: str, alias: str, state: Dict[str, Any]) -> None:
        """
        Replace or create the state document for a given (dex, alias).

        Args:
            dex: DEX identifier.
            alias: Vault alias.
            state: Full state payload to be stored in the 'state' field.
        """
        self._upsert_state_doc(dex, alias, state)

    def patch_state(self, dex: str, alias: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform a shallow merge of the provided updates into the 'state' field.

        If no state document exists yet, one is created with only the provided fields.

        Args:
            dex: DEX identifier.
            alias: Vault alias.
            updates: Partial state payload to merge into the existing state.

        Returns:
            The resulting state dictionary after the patch.
        """
        current_state = self.get_state(dex, alias)
        current_state.update(updates)
        self._upsert_state_doc(dex, alias, current_state)
        return current_state
