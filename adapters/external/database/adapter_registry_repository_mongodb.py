from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.mongo_client import get_mongo_db  # type: ignore
from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore
from core.domain.entities.adapter_registry_entity import AdapterRegistryEntity, AdapterStatus
from core.domain.repositories.adapter_registry_repository_interface import AdapterRegistryRepository


class AdapterRegistryRepositoryMongoDB(AdapterRegistryRepository):
    """
    Collection: adapter_registry

    Document shape:
    {
      "address": "0x..",  # deployed adapter contract address
      "tx_hash": "0x.." | null,

      "dex": "pancake_v3",

      "pool": "0x..",
      "nfpm": "0x..",
      "gauge": "0x..",  # may be zero

      "token0": "0x..",
      "token1": "0x..",
      "pool_name": "WETH/USDC",
      "fee_bps": "300",
      "status": "ACTIVE",

      "created_at": ISO string,
      "created_by": "0x.." | null
    }

    Uniqueness:
      - (dex, pool) unique: one adapter record per pool per dex.
      - address unique: avoid duplicates if the same deployment is inserted twice.
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
            [("dex", 1), ("pool", 1)],
            unique=True,
            name="ux_adapter_registry_dex_pool",
        )
        self._collection.create_index(
            [("address", 1)],
            unique=True,
            name="ux_adapter_registry_address",
        )
        self._collection.create_index([("status", 1)], name="ix_adapter_registry_status")
        self._collection.create_index([("created_at", -1)], name="ix_adapter_registry_created_at_desc")

    def _to_entity(self, doc: dict) -> AdapterRegistryEntity:
        return AdapterRegistryEntity(
            address=str(doc["address"]),
            dex=str(doc["dex"]),
            pool=str(doc["pool"]),
            nfpm=str(doc["nfpm"]),
            gauge=str(doc["gauge"]),
            token0=str(doc["token0"]),
            token1=str(doc["token1"]),
            pool_name=str(doc.get("pool_name") or ""),
            fee_bps=str(doc.get("fee_bps") or ""),
            status=AdapterStatus(str(doc["status"])),
            created_at=datetime.fromisoformat(doc["created_at"]),
            tx_hash=doc.get("tx_hash"),
            created_by=doc.get("created_by"),
        )

    def get_by_dex_pool(self, *, dex: str, pool: str) -> Optional[AdapterRegistryEntity]:
        doc = self._collection.find_one({"dex": dex, "pool": pool})
        return self._to_entity(doc) if doc else None

    def get_by_address(self, *, address: str) -> Optional[AdapterRegistryEntity]:
        doc = self._collection.find_one({"address": address})
        return self._to_entity(doc) if doc else None

    def insert(self, entity: AdapterRegistryEntity) -> None:
        doc = {
            "address": entity.address,
            "tx_hash": entity.tx_hash,
            "dex": entity.dex,
            "pool": entity.pool,
            "nfpm": entity.nfpm,
            "gauge": entity.gauge,
            "token0": entity.token0,
            "token1": entity.token1,
            "pool_name": entity.pool_name,
            "fee_bps": entity.fee_bps,
            "status": entity.status.value,
            "created_at": entity.created_at.isoformat(),
            "created_by": entity.created_by,
        }
        doc = sanitize_for_mongo(doc)
        self._collection.insert_one(doc)

    def list_all(self, *, limit: int = 100) -> Sequence[AdapterRegistryEntity]:
        cur = self._collection.find({}, sort=[("created_at", -1)]).limit(int(limit))
        return [self._to_entity(d) for d in cur]
