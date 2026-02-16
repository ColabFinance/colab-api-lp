# vault_fee_buffer_repository_mongodb.py

from __future__ import annotations

from typing import Optional, Sequence

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore
from adapters.external.database.mongo_client import get_mongo_db  # type: ignore
from core.domain.entities.vault_fee_buffer_entity import VaultFeeBufferEntity
from core.domain.enums.factory_enums import FactoryStatus
from core.domain.repositories.vault_fee_buffer_repository_interface import VaultFeeBufferRepository
from core.services.normalize import _norm_lower


class VaultFeeBufferRepositoryMongoDB(VaultFeeBufferRepository):
    """
    Collection: vault_fee_buffers
    """

    COLLECTION_NAME = "vault_fee_buffers"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db or get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index([("chain", 1)], name="ix_vault_fee_buffers_chain")
        self._collection.create_index([("status", 1)], name="ix_vault_fee_buffers_status")
        self._collection.create_index([("created_at", -1)], name="ix_vault_fee_buffers_created_at_desc")
        self._collection.create_index([("address", 1)], unique=True, name="ux_vault_fee_buffers_address")

    def get_latest(self, *, chain: str) -> Optional[VaultFeeBufferEntity]:
        doc = self._collection.find_one({"chain": _norm_lower(chain)}, sort=[("created_at", -1)])
        return VaultFeeBufferEntity.from_mongo(doc)

    def get_active(self, *, chain: str) -> Optional[VaultFeeBufferEntity]:
        doc = self._collection.find_one({"chain": _norm_lower(chain), "status": FactoryStatus.ACTIVE.value})
        return VaultFeeBufferEntity.from_mongo(doc)

    def insert(self, entity: VaultFeeBufferEntity) -> None:
        entity = entity.touch_for_insert()
        doc = sanitize_for_mongo(entity.to_mongo())

        for k in ("chain", "address", "tx_hash", "owner"):
            if k in doc and isinstance(doc.get(k), str):
                doc[k] = _norm_lower(doc.get(k))

        self._collection.insert_one(doc)

    def set_all_status(self, *, chain: str, status: FactoryStatus) -> int:
        res = self._collection.update_many({"chain": _norm_lower(chain)}, {"$set": {"status": status.value}})
        return int(res.modified_count)

    def list_all(self, *, chain: str, limit: int = 50) -> Sequence[VaultFeeBufferEntity]:
        cursor = self._collection.find({"chain": _norm_lower(chain)}, sort=[("created_at", -1)]).limit(int(limit))
        return [VaultFeeBufferEntity.from_mongo(d) for d in cursor if d]
