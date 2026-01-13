from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from config import get_settings
from core.domain.entities.factory_entities import VaultFactoryEntity, FactoryStatus
from core.domain.repositories.vault_factory_repository_interface import VaultFactoryRepository

from adapters.external.database.mongo_client import get_mongo_db  # type: ignore


class VaultFactoryRepositoryMongoDB(VaultFactoryRepository):
    """
    Collection: vault_factories
    """

    def __init__(self):
        s = get_settings()
        self.db = get_mongo_db(s.MONGO_URI, s.MONGO_DB)
        self.col = self.db["vault_factories"]
        self.col.create_index("status")
        self.col.create_index("created_at")

    def _to_entity(self, doc: dict) -> VaultFactoryEntity:
        return VaultFactoryEntity(
            address=str(doc["address"]),
            status=FactoryStatus(str(doc["status"])),
            created_at=datetime.fromisoformat(doc["created_at"]),
            tx_hash=doc.get("tx_hash"),
        )

    def get_latest(self) -> Optional[VaultFactoryEntity]:
        doc = self.col.find_one(sort=[("created_at", -1)])
        return self._to_entity(doc) if doc else None

    def get_active(self) -> Optional[VaultFactoryEntity]:
        doc = self.col.find_one({"status": FactoryStatus.ACTIVE.value})
        return self._to_entity(doc) if doc else None

    def insert(self, entity: VaultFactoryEntity) -> None:
        self.col.insert_one(
            {
                "address": entity.address,
                "status": entity.status.value,
                "created_at": entity.created_at.isoformat(),
                "tx_hash": entity.tx_hash,
            }
        )

    def set_all_status(self, *, status: FactoryStatus) -> int:
        res = self.col.update_many({}, {"$set": {"status": status.value}})
        return int(res.modified_count)

    def list_all(self, *, limit: int = 50) -> Sequence[VaultFactoryEntity]:
        cursor = self.col.find({}, sort=[("created_at", -1)]).limit(int(limit))
        return [self._to_entity(d) for d in cursor]
