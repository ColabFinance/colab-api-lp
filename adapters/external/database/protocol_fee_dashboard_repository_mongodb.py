from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.mongo_client import get_mongo_db
from core.services.normalize import _norm_lower


def _now_meta() -> tuple[int, str]:
    now = datetime.now(UTC)
    return int(now.timestamp()), now.isoformat()


def _serialize_doc(doc: Optional[dict]) -> Optional[dict]:
    if not doc:
        return None

    out = dict(doc)
    _id = out.pop("_id", None)
    if _id is not None:
        out["id"] = str(_id)
    return out


class ProtocolFeeTrackedTokenRepositoryMongoDB:
    COLLECTION_NAME = "protocol_fee_tracked_tokens"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db if db is not None else get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("chain", 1), ("contract_address", 1), ("token_address", 1)],
            unique=True,
            name="ux_protocol_fee_tracked_tokens_unique",
        )
        self._collection.create_index(
            [("chain", 1), ("contract_address", 1)],
            name="ix_protocol_fee_tracked_tokens_contract",
        )
        self._collection.create_index(
            [("updated_at", -1)],
            name="ix_protocol_fee_tracked_tokens_updated_desc",
        )

    def upsert(
        self,
        *,
        chain: str,
        contract_address: str,
        token_address: str,
        label: str | None,
        created_by: str | None,
    ) -> dict:
        ts, iso = _now_meta()

        flt = {
            "chain": _norm_lower(chain),
            "contract_address": _norm_lower(contract_address),
            "token_address": _norm_lower(token_address),
        }

        self._collection.update_one(
            flt,
            {
                "$set": {
                    "chain": _norm_lower(chain),
                    "contract_address": _norm_lower(contract_address),
                    "token_address": _norm_lower(token_address),
                    "label": (label or "").strip() or None,
                    "updated_at": ts,
                    "updated_at_iso": iso,
                },
                "$setOnInsert": {
                    "created_at": ts,
                    "created_at_iso": iso,
                    "created_by": _norm_lower(created_by) if created_by else None,
                },
            },
            upsert=True,
        )

        return _serialize_doc(self._collection.find_one(flt)) or {}

    def list_by_contract(
        self,
        *,
        chain: str,
        contract_address: str,
        limit: int = 300,
    ) -> list[dict]:
        cursor = self._collection.find(
            {
                "chain": _norm_lower(chain),
                "contract_address": _norm_lower(contract_address),
            },
            sort=[("updated_at", -1), ("token_address", 1)],
        ).limit(int(limit))

        return [_serialize_doc(doc) for doc in cursor if doc]


class ProtocolFeeWithdrawalRepositoryMongoDB:
    COLLECTION_NAME = "protocol_fee_withdrawals"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db if db is not None else get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("tx_hash", 1)],
            unique=True,
            name="ux_protocol_fee_withdrawals_tx_hash",
        )
        self._collection.create_index(
            [("chain", 1), ("contract_address", 1)],
            name="ix_protocol_fee_withdrawals_contract",
        )
        self._collection.create_index(
            [("created_at", -1)],
            name="ix_protocol_fee_withdrawals_created_desc",
        )

    def upsert(
        self,
        *,
        chain: str,
        contract_address: str,
        tx_hash: str,
        token_address: str,
        token_symbol: str | None,
        amount_raw: str,
        amount_label: str | None,
        destination: str,
        status: str,
        created_by: str | None,
    ) -> dict:
        ts, iso = _now_meta()

        flt = {"tx_hash": _norm_lower(tx_hash)}

        self._collection.update_one(
            flt,
            {
                "$set": {
                    "chain": _norm_lower(chain),
                    "contract_address": _norm_lower(contract_address),
                    "tx_hash": _norm_lower(tx_hash),
                    "token_address": _norm_lower(token_address),
                    "token_symbol": (token_symbol or "").strip() or None,
                    "amount_raw": str(amount_raw),
                    "amount_label": (amount_label or "").strip() or None,
                    "destination": _norm_lower(destination),
                    "status": (status or "").strip().lower(),
                    "updated_at": ts,
                    "updated_at_iso": iso,
                },
                "$setOnInsert": {
                    "created_at": ts,
                    "created_at_iso": iso,
                    "created_by": _norm_lower(created_by) if created_by else None,
                },
            },
            upsert=True,
        )

        return _serialize_doc(self._collection.find_one(flt)) or {}

    def list_by_contract(
        self,
        *,
        chain: str,
        contract_address: str,
        limit: int = 100,
    ) -> list[dict]:
        cursor = self._collection.find(
            {
                "chain": _norm_lower(chain),
                "contract_address": _norm_lower(contract_address),
            },
            sort=[("created_at", -1)],
        ).limit(int(limit))

        return [_serialize_doc(doc) for doc in cursor if doc]