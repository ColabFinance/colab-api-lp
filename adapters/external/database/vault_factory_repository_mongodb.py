from __future__ import annotations

from typing import Optional, Sequence

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore
from adapters.external.database.mongo_client import get_mongo_db  # type: ignore
from core.domain.entities.factory_entities import FactoryStatus, VaultFactoryEntity
from core.domain.repositories.vault_factory_repository_interface import VaultFactoryRepository


class VaultFactoryRepositoryMongoDB(VaultFactoryRepository):
    """
    Repository for VaultFactory records.

    Collection: vault_factories
    """

    COLLECTION_NAME = "vault_factories"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db or get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index([("chain", 1)], name="ix_vault_factories_chain")
        self._collection.create_index([("status", 1)], name="ix_vault_factories_status")
        self._collection.create_index([("created_at", -1)], name="ix_vault_factories_created_at_desc")
        self._collection.create_index([("address", 1)], unique=True, name="ux_vault_factories_address")

    def _touch_for_insert(self, entity: VaultFactoryEntity) -> VaultFactoryEntity:
        now_ms = entity.now_ms()
        now_iso = entity.now_iso()

        if entity.created_at is None:
            entity.created_at = now_ms
        if entity.created_at_iso is None:
            entity.created_at_iso = now_iso

        entity.updated_at = now_ms
        entity.updated_at_iso = now_iso
        return entity

    def get_latest(self, *, chain: str) -> Optional[VaultFactoryEntity]:
        doc = self._collection.find_one({"chain": chain}, sort=[("created_at", -1)])
        return VaultFactoryEntity.from_mongo(doc)

    def get_active(self, *, chain: str) -> Optional[VaultFactoryEntity]:
        doc = self._collection.find_one({"chain": chain, "status": FactoryStatus.ACTIVE.value})
        return VaultFactoryEntity.from_mongo(doc)

    def insert(self, entity: VaultFactoryEntity) -> None:
        entity = self._touch_for_insert(entity)
        doc = sanitize_for_mongo(entity.to_mongo())
        self._collection.insert_one(doc)

    def set_all_status(self, *, chain: str, status: FactoryStatus) -> int:
        res = self._collection.update_many({"chain": chain}, {"$set": {"status": status.value}})
        return int(res.modified_count)

    def list_all(self, *, chain: str, limit: int = 50) -> Sequence[VaultFactoryEntity]:
        cursor = self._collection.find({"chain": chain}, sort=[("created_at", -1)]).limit(int(limit))
        return [VaultFactoryEntity.from_mongo(d) for d in cursor if d]
