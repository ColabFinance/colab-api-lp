from __future__ import annotations

from typing import Optional, Sequence

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore
from adapters.external.database.mongo_client import get_mongo_db  # type: ignore

from core.domain.entities.dex_registry_entity import DexPoolEntity
from core.domain.enums.dex_registry_enums import DexRegistryStatus
from core.domain.repositories.dex_pool_repository_interface import DexPoolRepository


class DexPoolRepositoryMongoDB(DexPoolRepository):
    """
    Collection: dex_pools
    Unique key: (chain, dex, pool)
    """

    COLLECTION_NAME = "dex_pools"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db or get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index([("chain", 1)], name="ix_dex_pools_chain")
        self._collection.create_index([("dex", 1)], name="ix_dex_pools_dex")
        self._collection.create_index([("pool", 1)], name="ix_dex_pools_pool")
        self._collection.create_index([("status", 1)], name="ix_dex_pools_status")
        self._collection.create_index([("created_at", -1)], name="ix_dex_pools_created_at_desc")
        self._collection.create_index([("chain", 1), ("dex", 1), ("pool", 1)], unique=True, name="ux_dex_pools_chain_dex_pool")

        # Optional: ensure adapter unique when present
        self._collection.create_index(
            [("adapter", 1)],
            unique=True,
            name="ux_dex_pools_adapter_nonnull",
            partialFilterExpression={"adapter": {"$type": "string", "$gt": ""}},
        )

    def get_by_pool(self, *, chain: str, dex: str, pool: str) -> Optional[DexPoolEntity]:
        doc = self._collection.find_one({"chain": chain, "dex": dex, "pool": pool})
        return DexPoolEntity.from_mongo(doc)

    def insert(self, entity: DexPoolEntity) -> None:
        entity = entity.touch_for_insert()
        doc = sanitize_for_mongo(entity.to_mongo())
        self._collection.insert_one(doc)

    def list_by_dex(self, *, chain: str, dex: str, limit: int = 500) -> Sequence[DexPoolEntity]:
        cursor = (
            self._collection.find({"chain": chain, "dex": dex}, sort=[("created_at", -1)])
            .limit(int(limit))
        )
        return [DexPoolEntity.from_mongo(d) for d in cursor if d]

    def set_status(self, *, chain: str, dex: str, pool: str, status: DexRegistryStatus) -> int:
        res = self._collection.update_one(
            {"chain": chain, "dex": dex, "pool": pool},
            {"$set": {"status": status.value}},
        )
        return int(res.modified_count)

    def set_adapter(self, *, chain: str, dex: str, pool: str, adapter: str) -> int:
        res = self._collection.update_one(
            {"chain": chain, "dex": dex, "pool": pool},
            {"$set": {"adapter": adapter}},
        )
        return int(res.modified_count)

    def get_by_pool_address(self, *, pool: str) -> Optional[DexPoolEntity]:
        doc = self._collection.find_one({"pool": pool})
        return DexPoolEntity.from_mongo(doc)