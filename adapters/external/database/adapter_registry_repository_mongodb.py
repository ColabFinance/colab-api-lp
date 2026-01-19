from __future__ import annotations

from typing import Optional, Sequence

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore
from adapters.external.database.mongo_client import get_mongo_db  # type: ignore
from core.domain.entities.adapter_registry_entity import AdapterRegistryEntity
from core.domain.enums.adapter_enums import AdapterStatus
from core.domain.repositories.adapter_registry_repository_interface import AdapterRegistryRepository


class AdapterRegistryRepositoryMongoDB(AdapterRegistryRepository):
    """
    Collection: adapter_registry

    Uniqueness:
    - (chain, dex, pool) unique
    - address unique
    """

    COLLECTION_NAME = "adapter_registry"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db or get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("chain", 1), ("dex", 1), ("pool", 1)],
            unique=True,
            name="ux_adapter_registry_chain_dex_pool",
        )
        self._collection.create_index([("address", 1)], unique=True, name="ux_adapter_registry_address")
        self._collection.create_index([("chain", 1)], name="ix_adapter_registry_chain")
        self._collection.create_index([("status", 1)], name="ix_adapter_registry_status")
        self._collection.create_index([("created_at", -1)], name="ix_adapter_registry_created_at_desc")

    def _touch_for_insert(self, entity: AdapterRegistryEntity) -> AdapterRegistryEntity:
        now_ms = entity.now_ms()
        now_iso = entity.now_iso()

        if entity.created_at is None:
            entity.created_at = now_ms
        if entity.created_at_iso is None:
            entity.created_at_iso = now_iso

        entity.updated_at = now_ms
        entity.updated_at_iso = now_iso
        return entity

    def get_by_dex_pool(self, *, chain: str, dex: str, pool: str) -> Optional[AdapterRegistryEntity]:
        doc = self._collection.find_one({"chain": chain, "dex": dex, "pool": pool})
        return AdapterRegistryEntity.from_mongo(doc)

    def get_by_address(self, *, address: str) -> Optional[AdapterRegistryEntity]:
        doc = self._collection.find_one({"address": address})
        return AdapterRegistryEntity.from_mongo(doc)

    def insert(self, entity: AdapterRegistryEntity) -> None:
        entity = self._touch_for_insert(entity)
        doc = sanitize_for_mongo(entity.to_mongo())
        self._collection.insert_one(doc)

    def list_all(self, *, chain: str | None = None, limit: int = 100) -> Sequence[AdapterRegistryEntity]:
        q: dict = {}
        if chain:
            q["chain"] = chain
        cur = self._collection.find(q, sort=[("created_at", -1)]).limit(int(limit))
        return [AdapterRegistryEntity.from_mongo(d) for d in cur if d]

    def list_active(self, *, chain: str, limit: int = 200) -> Sequence[AdapterRegistryEntity]:
        cur = (
            self._collection.find(
                {"chain": chain, "status": AdapterStatus.ACTIVE.value},
                sort=[("created_at", -1)],
            )
            .limit(int(limit))
        )
        return [AdapterRegistryEntity.from_mongo(d) for d in cur if d]
