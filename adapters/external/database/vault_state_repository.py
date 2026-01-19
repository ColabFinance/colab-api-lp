from __future__ import annotations

from typing import Any, Dict, Optional

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo
from adapters.external.database.mongo_client import get_mongo_db
from core.domain.entities.vault_state_entity import VaultStateDocument
from core.domain.repositories.vault_state_repository_interface import VaultStateRepositoryInterface


class VaultStateRepository(VaultStateRepositoryInterface):
    """
    Repository responsible for storing and retrieving the *current* vault state.

    Collection: vault_state
    """

    COLLECTION_NAME = "vault_state"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db or get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("dex", 1), ("alias", 1)],
            unique=True,
            name="ux_vault_state_dex_alias",
        )

    def _get_state_doc(self, dex: str, alias: str) -> Optional[VaultStateDocument]:
        doc = self._collection.find_one({"dex": dex, "alias": alias})
        return VaultStateDocument.from_mongo(doc)

    def _upsert_state_doc(self, dex: str, alias: str, state: Dict[str, Any]) -> VaultStateDocument:
        existing = self._collection.find_one({"dex": dex, "alias": alias})

        if existing:
            entity = VaultStateDocument.from_mongo(existing)
            if entity is None:
                raise RuntimeError("Failed to parse an existing vault_state document.")

            entity.state = state

            now_ms = entity.now_ms()
            now_iso = entity.now_iso()

            # preserve created_* if present, otherwise set (defensive)
            if entity.created_at is None:
                entity.created_at = now_ms
            if entity.created_at_iso is None:
                entity.created_at_iso = now_iso

            entity.updated_at = now_ms
            entity.updated_at_iso = now_iso

            self._collection.update_one(
                {"_id": existing["_id"]},
                {"$set": sanitize_for_mongo(entity.to_mongo())},
            )
            return entity

        entity = VaultStateDocument(dex=dex, alias=alias, state=state)

        now_ms = entity.now_ms()
        now_iso = entity.now_iso()
        entity.created_at = now_ms
        entity.created_at_iso = now_iso
        entity.updated_at = now_ms
        entity.updated_at_iso = now_iso

        mongo_doc = sanitize_for_mongo(entity.to_mongo())
        res = self._collection.insert_one(mongo_doc)

        saved = dict(mongo_doc)
        saved["_id"] = res.inserted_id
        parsed = VaultStateDocument.from_mongo(saved)
        if parsed is None:
            raise RuntimeError("Failed to parse inserted vault_state document.")
        return parsed

    def get_state(self, dex: str, alias: str) -> Dict[str, Any]:
        entity = self._get_state_doc(dex, alias)
        if entity is None:
            return {}
        return entity.state or {}

    def upsert_state(self, dex: str, alias: str, state: Dict[str, Any]) -> None:
        self._upsert_state_doc(dex, alias, state)

    def patch_state(self, dex: str, alias: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        current_state = self.get_state(dex, alias)
        current_state.update(updates)
        self._upsert_state_doc(dex, alias, current_state)
        return current_state
