from __future__ import annotations

from typing import Optional, Sequence

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore
from adapters.external.database.mongo_client import get_mongo_db  # type: ignore
from core.domain.entities.factory_entities import StrategyFactoryEntity
from core.domain.enums.factory_enums import FactoryStatus
from core.domain.repositories.strategy_factory_repository_interface import StrategyRepository


class StrategyRepositoryMongoDB(StrategyRepository):
    """
    Repository for StrategyRegistry factory records.

    Collection: strategy_factories
    """

    COLLECTION_NAME = "strategy_factories"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db or get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index([("chain", 1)], name="ix_strategy_factories_chain")
        self._collection.create_index([("status", 1)], name="ix_strategy_factories_status")
        self._collection.create_index([("created_at", -1)], name="ix_strategy_factories_created_at_desc")
        self._collection.create_index([("address", 1)], unique=True, name="ux_strategy_factories_address")

    def get_latest(self, *, chain: str) -> Optional[StrategyFactoryEntity]:
        doc = self._collection.find_one({"chain": chain}, sort=[("created_at", -1)])
        return StrategyFactoryEntity.from_mongo(doc)

    def get_active(self, *, chain: str) -> Optional[StrategyFactoryEntity]:
        doc = self._collection.find_one({"chain": chain, "status": FactoryStatus.ACTIVE.value})
        return StrategyFactoryEntity.from_mongo(doc)

    def insert(self, entity: StrategyFactoryEntity) -> None:
        entity = entity.touch_for_insert()
        doc = sanitize_for_mongo(entity.to_mongo())
        self._collection.insert_one(doc)

    def set_all_status(self, *, chain: str, status: FactoryStatus) -> int:
        res = self._collection.update_many({"chain": chain}, {"$set": {"status": status.value}})
        return int(res.modified_count)

    def list_all(self, *, chain: str, limit: int = 50) -> Sequence[StrategyFactoryEntity]:
        cursor = self._collection.find({"chain": chain}, sort=[("created_at", -1)]).limit(int(limit))
        return [StrategyFactoryEntity.from_mongo(d) for d in cursor if d]
