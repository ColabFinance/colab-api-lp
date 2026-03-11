from __future__ import annotations

import re
from typing import Optional, Sequence

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo
from adapters.external.database.mongo_client import get_mongo_db

from core.domain.entities.chain_registry_entity import ChainRegistryEntity
from core.domain.repositories.chain_registry_repository_interface import ChainRegistryRepository


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def _norm_symbol(value: str) -> str:
    return (value or "").strip().upper()


def _norm_stables(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for item in values or []:
        symbol = _norm_symbol(item)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(symbol)

    return result


class ChainRegistryRepositoryMongoDB(ChainRegistryRepository):
    COLLECTION_NAME = "chain_registries"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db: Database = db if db is not None else get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index([("key", 1)], unique=True, name="ux_chain_registries_key")
        self._collection.create_index([("chain_id", 1)], unique=True, name="ux_chain_registries_chain_id")
        self._collection.create_index([("status", 1)], name="ix_chain_registries_status")
        self._collection.create_index([("updated_at", -1)], name="ix_chain_registries_updated_at_desc")
        self._collection.create_index([("created_at", -1)], name="ix_chain_registries_created_at_desc")

    def get_by_key(self, *, key: str) -> Optional[ChainRegistryEntity]:
        doc = self._collection.find_one({"key": _slugify(key)})
        return ChainRegistryEntity.from_mongo(doc)

    def get_by_chain_id(self, *, chain_id: int) -> Optional[ChainRegistryEntity]:
        doc = self._collection.find_one({"chain_id": int(chain_id)})
        return ChainRegistryEntity.from_mongo(doc)

    def insert(self, entity: ChainRegistryEntity) -> None:
        entity = entity.touch_for_insert()
        doc = sanitize_for_mongo(entity.to_mongo())

        doc["key"] = _slugify(doc.get("key", ""))
        doc["native_symbol"] = _norm_symbol(doc.get("native_symbol", ""))
        doc["stables"] = _norm_stables(doc.get("stables", []))
        doc["logo_url"] = (doc.get("logo_url") or "").strip()

        self._collection.insert_one(doc)

    def update(self, entity: ChainRegistryEntity) -> None:
        entity = entity.touch_for_update()
        doc = sanitize_for_mongo(entity.to_mongo())
        doc.pop("_id", None)

        doc["key"] = _slugify(doc.get("key", ""))
        doc["native_symbol"] = _norm_symbol(doc.get("native_symbol", ""))
        doc["stables"] = _norm_stables(doc.get("stables", []))
        doc["logo_url"] = (doc.get("logo_url") or "").strip()

        self._collection.update_one(
            {"key": doc["key"]},
            {"$set": doc},
            upsert=False,
        )

    def list_all(self, *, limit: int = 200) -> Sequence[ChainRegistryEntity]:
        cursor = (
            self._collection
            .find({}, sort=[("updated_at", -1), ("created_at", -1)])
            .limit(int(limit))
        )
        return [ChainRegistryEntity.from_mongo(doc) for doc in cursor if doc]