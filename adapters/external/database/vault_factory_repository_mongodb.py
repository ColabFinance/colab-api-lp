from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.mongo_client import get_mongo_db  # type: ignore
from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore

from core.domain.entities.factory_entities import VaultFactoryEntity, FactoryStatus
from core.domain.repositories.vault_factory_repository_interface import VaultFactoryRepository


class VaultFactoryRepositoryMongoDB(VaultFactoryRepository):
    """
    Repository for VaultFactory (on-chain) factory records.

    Collection: vault_factories
    """

    COLLECTION_NAME = "vault_factories"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db or get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("status", 1)],
            name="ix_vault_factories_status",
        )
        self._collection.create_index(
            [("created_at", -1)],
            name="ix_vault_factories_created_at_desc",
        )

    def _to_entity(self, doc: dict) -> VaultFactoryEntity:
        return VaultFactoryEntity(
            address=str(doc["address"]),
            status=FactoryStatus(str(doc["status"])),
            created_at=datetime.fromisoformat(doc["created_at"]),
            tx_hash=doc.get("tx_hash"),
        )

    def get_latest(self) -> Optional[VaultFactoryEntity]:
        doc = self._collection.find_one(sort=[("created_at", -1)])
        return self._to_entity(doc) if doc else None

    def get_active(self) -> Optional[VaultFactoryEntity]:
        doc = self._collection.find_one({"status": FactoryStatus.ACTIVE.value})
        return self._to_entity(doc) if doc else None

    def insert(self, entity: VaultFactoryEntity) -> None:
        doc = {
            "address": entity.address,
            "status": entity.status.value,
            "created_at": entity.created_at.isoformat(),
            "tx_hash": entity.tx_hash,
        }
        doc = sanitize_for_mongo(doc)
        self._collection.insert_one(doc)

    def set_all_status(self, *, status: FactoryStatus) -> int:
        res = self._collection.update_many({}, {"$set": {"status": status.value}})
        return int(res.modified_count)

    def list_all(self, *, limit: int = 50) -> Sequence[VaultFactoryEntity]:
        cursor = (
            self._collection
            .find({}, sort=[("created_at", -1)])
            .limit(int(limit))
        )
        return [self._to_entity(d) for d in cursor]
