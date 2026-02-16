# vault_user_events_repository_mongodb.py

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore
from adapters.external.database.mongo_client import get_mongo_db  # type: ignore
from core.domain.entities.vault_user_event_entity import VaultUserEventEntity
from core.services.normalize import _norm_lower


class VaultUserEventsRepositoryMongoDB:
    COLLECTION_NAME = "vault_user_events"
    COLLECTION = COLLECTION_NAME

    def __init__(self, db: Optional[Database] = None, col: Optional[Collection] = None) -> None:
        if col is not None:
            self._col = col
            self._db = col.database
        else:
            self._db = db if db is not None else get_mongo_db()
            self._col = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._col

    def ensure_indexes(self) -> None:
        self._col.create_index([("chain", 1), ("tx_hash", 1), ("event_type", 1)], unique=True, name="ux_chain_tx_type")
        self._col.create_index([("vault", 1), ("ts_ms", -1)], name="ix_vault_ts_desc")
        self._col.create_index([("owner", 1), ("ts_ms", -1)], name="ix_owner_ts_desc")

    def _normalize_doc(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        for k in ("vault", "alias", "chain", "dex", "event_type", "owner", "token", "to", "tx_hash"):
            if k in doc and isinstance(doc.get(k), str):
                doc[k] = _norm_lower(doc.get(k))

        transfers = doc.get("transfers")
        if isinstance(transfers, list):
            for tr in transfers:
                if not isinstance(tr, dict):
                    continue
                for k in ("token", "from", "to", "symbol", "price_usd", "amount_raw", "amount_human"):
                    if k in tr and isinstance(tr.get(k), str):
                        tr[k] = _norm_lower(tr.get(k))

        return doc

    def upsert_idempotent(self, entity: VaultUserEventEntity) -> VaultUserEventEntity:
        entity = entity.touch_for_insert()
        doc = sanitize_for_mongo(entity.to_mongo())
        doc = self._normalize_doc(doc)

        # ensure event timestamps exist
        if doc.get("ts_ms") is None:
            doc["ts_ms"] = int(entity.now_ms())
        if doc.get("ts_iso") is None:
            doc["ts_iso"] = str(entity.now_iso())

        q = {
            "chain": doc.get("chain"),
            "tx_hash": doc.get("tx_hash"),
            "event_type": doc.get("event_type"),
        }

        saved = self._col.find_one_and_update(
            q,
            {"$setOnInsert": doc, "$set": {"updated_at": entity.now_ms(), "updated_at_iso": entity.now_iso()}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return VaultUserEventEntity.from_mongo(saved)

    def list_by_vault(self, *, vault: str, limit: int, offset: int) -> List[VaultUserEventEntity]:
        v = _norm_lower(vault)
        cur = (
            self._col.find({"vault": v})
            .sort("ts_ms", -1)
            .skip(int(offset or 0))
            .limit(int(limit or 50))
        )
        docs = list(cur)
        return [VaultUserEventEntity.from_mongo(d) for d in docs if d]

    def count_by_vault(self, *, vault: str) -> int:
        v = _norm_lower(vault)
        return int(self._col.count_documents({"vault": v}))
