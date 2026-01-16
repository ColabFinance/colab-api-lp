# adapters/external/database/vault_registry_repository_mongodb.py

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from pymongo.collection import Collection

from core.domain.entities.vault_client_registry_entity import VaultRegistryEntity
from core.domain.repositories.vault_client_registry_repository_interface import VaultRegistryRepositoryInterface


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_iso() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


class VaultRegistryRepositoryMongoDB(VaultRegistryRepositoryInterface):
    COLLECTION = "vault_registry"

    def __init__(self, col: Collection):
        self._col = col

    def ensure_indexes(self) -> None:
        # alias must be unique
        self._col.create_index([("alias", 1)], unique=True, name="ux_alias")

        # helpful search indexes
        self._col.create_index([("chain", 1), ("dex", 1), ("owner", 1)], name="ix_chain_dex_owner")
        self._col.create_index([("created_at", -1)], name="ix_created_at_desc")

    def insert(self, entity: VaultRegistryEntity) -> VaultRegistryEntity:
        doc = entity.to_mongo()

        # timestamps
        now_ms = _now_ms()
        now_iso = _now_iso()

        doc.setdefault("created_at", now_ms)
        doc.setdefault("created_at_iso", now_iso)
        doc["updated_at"] = now_ms
        doc["updated_at_iso"] = now_iso

        res = self._col.insert_one(doc)
        saved = dict(doc)
        saved["_id"] = res.inserted_id
        return VaultRegistryEntity.from_mongo(saved)

    def find_by_alias(self, alias: str) -> Optional[VaultRegistryEntity]:
        doc = self._col.find_one({"alias": alias})
        return VaultRegistryEntity.from_mongo(doc)

    def count_alias_prefix(self, *, chain: str, dex: str, owner_prefix: str, par_token: str) -> int:
        """
        Count existing docs that match the alias prefix pattern.
        We rely on regex anchored at beginning.
        """
        # pattern: {owner5}-{parToken}-{dex}-{chain}-{N}
        # we count docs that start with that prefix (up to the last dash)
        prefix = f"{owner_prefix}-{par_token}-{dex}-{chain}-"
        return int(self._col.count_documents({"alias": {"$regex": f"^{prefix}"}}))
