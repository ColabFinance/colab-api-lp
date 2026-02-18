from __future__ import annotations

from typing import Optional, Sequence

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore
from adapters.external.database.mongo_client import get_mongo_db  # type: ignore
from core.domain.entities.adapter_registry_entity import AdapterRegistryEntity
from core.domain.enums.adapter_enums import AdapterStatus
from core.domain.repositories.adapter_registry_repository_interface import AdapterRegistryRepository

from core.services.normalize import _norm_lower


class AdapterRegistryRepositoryMongoDB(AdapterRegistryRepository):
    COLLECTION_NAME = "adapter_registry"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db if db is not None else get_mongo_db()
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

    def get_by_dex_pool(self, *, chain: str, dex: str, pool: str) -> Optional[AdapterRegistryEntity]:
        doc = self._collection.find_one(
            {"chain": _norm_lower(chain), "dex": _norm_lower(dex), "pool": _norm_lower(pool)}
        )
        return AdapterRegistryEntity.from_mongo(doc)

    def get_by_address(self, *, address: str) -> Optional[AdapterRegistryEntity]:
        doc = self._collection.find_one({"address": _norm_lower(address)})
        return AdapterRegistryEntity.from_mongo(doc)

    def insert(self, entity: AdapterRegistryEntity) -> None:
        entity = entity.touch_for_insert()
        doc = sanitize_for_mongo(entity.to_mongo())

        # enforce lowercase storage for keys
        for k in ("chain", "dex", "pool", "address", "nfpm", "gauge", "fee_buffer", "token0", "token1", "tx_hash", "created_by"):
            if k in doc and isinstance(doc.get(k), str):
                doc[k] = _norm_lower(doc.get(k))

        self._collection.insert_one(doc)

    def list_all(self, *, chain: str | None = None, limit: int = 100) -> Sequence[AdapterRegistryEntity]:
        q: dict = {}
        if chain:
            q["chain"] = _norm_lower(chain)
        cur = self._collection.find(q, sort=[("created_at", -1)]).limit(int(limit))
        return [AdapterRegistryEntity.from_mongo(d) for d in cur if d]

    def list_active(self, *, chain: str, limit: int = 200) -> Sequence[AdapterRegistryEntity]:
        cur = (
            self._collection.find(
                {"chain": _norm_lower(chain), "status": AdapterStatus.ACTIVE.value},
                sort=[("created_at", -1)],
            )
            .limit(int(limit))
        )
        return [AdapterRegistryEntity.from_mongo(d) for d in cur if d]
