from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from pymongo.collection import Collection
from pymongo import ReturnDocument
from web3 import Web3

from core.domain.entities.vault_user_event_entity import VaultUserEventEntity
from core.domain.repositories.vault_user_events_repository_interface import VaultUserEventsRepositoryInterface


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_iso() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


class VaultUserEventsRepositoryMongoDB:
    COLLECTION = "vault_user_events"

    def __init__(self, col: Collection):
        self._col = col

    def ensure_indexes(self) -> None:
        # idempotency
        self._col.create_index([("chain", 1), ("tx_hash", 1), ("event_type", 1)], unique=True, name="ux_chain_tx_type")
        self._col.create_index([("vault", 1), ("ts_ms", -1)], name="ix_vault_ts_desc")
        self._col.create_index([("owner", 1), ("ts_ms", -1)], name="ix_owner_ts_desc")

    def upsert_idempotent(self, entity: VaultUserEventEntity) -> VaultUserEventEntity:
        doc = entity.to_mongo()

        now_ms = _now_ms()
        now_iso = _now_iso()

        doc.setdefault("ts_ms", now_ms)
        doc.setdefault("ts_iso", now_iso)

        q = {"chain": doc.get("chain"), "tx_hash": doc.get("tx_hash"), "event_type": doc.get("event_type")}

        saved = self._col.find_one_and_update(
            q,
            {"$setOnInsert": doc, "$set": {"updated_at": now_ms, "updated_at_iso": now_iso}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return VaultUserEventEntity.from_mongo(saved)

    def list_by_vault(self, *, vault: str, limit: int, offset: int) -> List[VaultUserEventEntity]:
        v = (vault or "").strip()
        if Web3.is_address(v):
            v = Web3.to_checksum_address(v)

        cur = (
            self._col.find({"vault": v})
            .sort("ts_ms", -1)
            .skip(int(offset or 0))
            .limit(int(limit or 50))
        )
        docs = list(cur)
        return [VaultUserEventEntity.from_mongo(d) for d in docs if d]

    def count_by_vault(self, *, vault: str) -> int:
        v = (vault or "").strip()
        if Web3.is_address(v):
            v = Web3.to_checksum_address(v)
        return int(self._col.count_documents({"vault": v}))
