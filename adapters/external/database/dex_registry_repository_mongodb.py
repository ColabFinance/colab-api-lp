from __future__ import annotations

from typing import Optional, Sequence

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore
from adapters.external.database.mongo_client import get_mongo_db  # type: ignore

from core.domain.entities.dex_registry_entity import DexRegistryEntity
from core.domain.enums.dex_registry_enums import DexRegistryStatus
from core.domain.repositories.dex_registry_repository_interface import DexRegistryRepository
from core.services.normalize import _norm_lower


class DexRegistryRepositoryMongoDB(DexRegistryRepository):
    COLLECTION_NAME = "dex_registries"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db if db is not None else get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index([("chain", 1)], name="ix_dex_registries_chain")
        self._collection.create_index([("dex", 1)], name="ix_dex_registries_dex")
        self._collection.create_index([("status", 1)], name="ix_dex_registries_status")
        self._collection.create_index([("created_at", -1)], name="ix_dex_registries_created_at_desc")
        self._collection.create_index([("chain", 1), ("dex", 1)], unique=True, name="ux_dex_registries_chain_dex")

    def get_by_key(self, *, chain: str, dex: str) -> Optional[DexRegistryEntity]:
        doc = self._collection.find_one({"chain": _norm_lower(chain), "dex": _norm_lower(dex)})
        return DexRegistryEntity.from_mongo(doc)

    def insert(self, entity: DexRegistryEntity) -> None:
        entity = entity.touch_for_insert()
        doc = sanitize_for_mongo(entity.to_mongo())

        for k in ("chain", "dex", "dex_router"):
            if k in doc and isinstance(doc.get(k), str):
                doc[k] = _norm_lower(doc.get(k))

        self._collection.insert_one(doc)

    def update_by_key(
        self,
        *,
        chain: str,
        dex: str,
        dex_router: str,
        status: DexRegistryStatus,
    ) -> Optional[DexRegistryEntity]:
        current = self.get_by_key(chain=chain, dex=dex)
        if current is None:
            return None

        touched = current.touch_for_update()
        status_value = status.value if isinstance(status, DexRegistryStatus) else str(status)

        patch = sanitize_for_mongo(
            {
                "dex_router": _norm_lower(dex_router),
                "status": status_value,
                "updated_at": touched.updated_at,
                "updated_at_iso": touched.updated_at_iso,
            }
        )

        self._collection.update_one(
            {"chain": _norm_lower(chain), "dex": _norm_lower(dex)},
            {"$set": patch},
        )
        return self.get_by_key(chain=chain, dex=dex)

    def list_all(self, *, chain: str, limit: int = 200) -> Sequence[DexRegistryEntity]:
        cursor = self._collection.find({"chain": _norm_lower(chain)}, sort=[("created_at", -1)]).limit(int(limit))
        return [DexRegistryEntity.from_mongo(d) for d in cursor if d]