# vault_factory_repository_mongodb.py

from __future__ import annotations

from typing import Optional, Sequence

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore
from adapters.external.database.mongo_client import get_mongo_db  # type: ignore
from core.domain.entities.factory_entities import VaultFactoryEntity
from core.domain.enums.factory_enums import FactoryStatus
from core.domain.repositories.vault_factory_repository_interface import VaultFactoryRepository
from core.services.normalize import _norm_lower


class VaultFactoryRepositoryMongoDB(VaultFactoryRepository):
    """
    Repository for VaultFactory records.

    Collection: vault_factories
    """

    COLLECTION_NAME = "vault_factories"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db if db is not None else get_mongo_db()
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

    def get_latest(self, *, chain: str) -> Optional[VaultFactoryEntity]:
        doc = self._collection.find_one({"chain": _norm_lower(chain)}, sort=[("created_at", -1)])
        return VaultFactoryEntity.from_mongo(doc)

    def get_active(self, *, chain: str) -> Optional[VaultFactoryEntity]:
        doc = self._collection.find_one({"chain": _norm_lower(chain), "status": FactoryStatus.ACTIVE.value})
        return VaultFactoryEntity.from_mongo(doc)

    def insert(self, entity: VaultFactoryEntity) -> None:
        entity = entity.touch_for_insert()
        doc = sanitize_for_mongo(entity.to_mongo())

        for k in ("chain", "address", "tx_hash"):
            if k in doc and isinstance(doc.get(k), str):
                doc[k] = _norm_lower(doc.get(k))

        self._collection.insert_one(doc)

    def set_all_status(self, *, chain: str, status: FactoryStatus) -> int:
        res = self._collection.update_many({"chain": _norm_lower(chain)}, {"$set": {"status": status.value}})
        return int(res.modified_count)

    def list_all(self, *, chain: str, limit: int = 50) -> Sequence[VaultFactoryEntity]:
        cursor = self._collection.find({"chain": _norm_lower(chain)}, sort=[("created_at", -1)]).limit(int(limit))
        return [VaultFactoryEntity.from_mongo(d) for d in cursor if d]
