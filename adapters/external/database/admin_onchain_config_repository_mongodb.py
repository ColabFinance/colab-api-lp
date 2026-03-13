from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

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


class StrategyRegistryAllowlistRepositoryMongoDB:
    COLLECTION_NAME = "admin_strategy_registry_allowlists"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db if db is not None else get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("chain", 1), ("contract_address", 1), ("entry_type", 1), ("address", 1)],
            unique=True,
            name="ux_admin_strategy_registry_allowlists_unique",
        )
        self._collection.create_index(
            [("chain", 1), ("contract_address", 1), ("entry_type", 1)],
            name="ix_admin_strategy_registry_allowlists_contract_type",
        )
        self._collection.create_index(
            [("updated_at", -1)],
            name="ix_admin_strategy_registry_allowlists_updated_desc",
        )

    def upsert(
        self,
        *,
        chain: str,
        contract_address: str,
        entry_type: str,
        address: str,
        label: str,
        adapter_type: str | None,
        desired_allowed: bool,
        tx_hash: str | None,
        updated_by: str | None,
    ) -> dict:
        ts, iso = _now_meta()

        chain_norm = _norm_lower(chain)
        contract_norm = _norm_lower(contract_address)
        entry_type_norm = _norm_lower(entry_type)
        address_norm = _norm_lower(address)

        flt = {
            "chain": chain_norm,
            "contract_address": contract_norm,
            "entry_type": entry_type_norm,
            "address": address_norm,
        }

        self._collection.update_one(
            flt,
            {
                "$set": {
                    "chain": chain_norm,
                    "contract_address": contract_norm,
                    "entry_type": entry_type_norm,
                    "address": address_norm,
                    "label": (label or "").strip(),
                    "adapter_type": (adapter_type or "").strip() or None,
                    "desired_allowed": bool(desired_allowed),
                    "tx_hash": _norm_lower(tx_hash) if tx_hash else None,
                    "updated_by": _norm_lower(updated_by) if updated_by else None,
                    "updated_at": ts,
                    "updated_at_iso": iso,
                },
                "$setOnInsert": {
                    "created_at": ts,
                    "created_at_iso": iso,
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
        entry_type: str,
        limit: int = 500,
    ) -> list[dict]:
        cursor = self._collection.find(
            {
                "chain": _norm_lower(chain),
                "contract_address": _norm_lower(contract_address),
                "entry_type": _norm_lower(entry_type),
            },
            sort=[("label", 1), ("updated_at", -1)],
        ).limit(int(limit))

        return [_serialize_doc(doc) for doc in cursor if doc]


class VaultFactoryConfigRepositoryMongoDB:
    COLLECTION_NAME = "admin_vault_factory_configs"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db if db is not None else get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("chain", 1), ("contract_address", 1)],
            unique=True,
            name="ux_admin_vault_factory_configs_contract",
        )
        self._collection.create_index(
            [("updated_at", -1)],
            name="ix_admin_vault_factory_configs_updated_desc",
        )

    def upsert(
        self,
        *,
        chain: str,
        contract_address: str,
        executor: str,
        fee_collector: str,
        default_cooldown_sec: int,
        default_max_slippage_bps: int,
        default_allow_swap: bool,
        tx_hash: str | None,
        updated_by: str | None,
    ) -> dict:
        ts, iso = _now_meta()

        flt = {
            "chain": _norm_lower(chain),
            "contract_address": _norm_lower(contract_address),
        }

        self._collection.update_one(
            flt,
            {
                "$set": {
                    "chain": _norm_lower(chain),
                    "contract_address": _norm_lower(contract_address),
                    "executor": _norm_lower(executor),
                    "fee_collector": _norm_lower(fee_collector),
                    "default_cooldown_sec": int(default_cooldown_sec),
                    "default_max_slippage_bps": int(default_max_slippage_bps),
                    "default_allow_swap": bool(default_allow_swap),
                    "tx_hash": _norm_lower(tx_hash) if tx_hash else None,
                    "updated_by": _norm_lower(updated_by) if updated_by else None,
                    "updated_at": ts,
                    "updated_at_iso": iso,
                },
                "$setOnInsert": {
                    "created_at": ts,
                    "created_at_iso": iso,
                },
            },
            upsert=True,
        )

        return _serialize_doc(self._collection.find_one(flt)) or {}

    def get_by_contract(self, *, chain: str, contract_address: str) -> Optional[dict]:
        return _serialize_doc(
            self._collection.find_one(
                {
                    "chain": _norm_lower(chain),
                    "contract_address": _norm_lower(contract_address),
                }
            )
        )


class ProtocolFeeCollectorConfigRepositoryMongoDB:
    COLLECTION_NAME = "admin_protocol_fee_collector_configs"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db if db is not None else get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("chain", 1), ("contract_address", 1)],
            unique=True,
            name="ux_admin_protocol_fee_collector_configs_contract",
        )
        self._collection.create_index(
            [("updated_at", -1)],
            name="ix_admin_protocol_fee_collector_configs_updated_desc",
        )

    def upsert(
        self,
        *,
        chain: str,
        contract_address: str,
        treasury: str,
        protocol_fee_bps: int,
        tx_hash: str | None,
        updated_by: str | None,
    ) -> dict:
        ts, iso = _now_meta()

        flt = {
            "chain": _norm_lower(chain),
            "contract_address": _norm_lower(contract_address),
        }

        self._collection.update_one(
            flt,
            {
                "$set": {
                    "chain": _norm_lower(chain),
                    "contract_address": _norm_lower(contract_address),
                    "treasury": _norm_lower(treasury),
                    "protocol_fee_bps": int(protocol_fee_bps),
                    "tx_hash": _norm_lower(tx_hash) if tx_hash else None,
                    "updated_by": _norm_lower(updated_by) if updated_by else None,
                    "updated_at": ts,
                    "updated_at_iso": iso,
                },
                "$setOnInsert": {
                    "created_at": ts,
                    "created_at_iso": iso,
                },
            },
            upsert=True,
        )

        return _serialize_doc(self._collection.find_one(flt)) or {}

    def get_by_contract(self, *, chain: str, contract_address: str) -> Optional[dict]:
        return _serialize_doc(
            self._collection.find_one(
                {
                    "chain": _norm_lower(chain),
                    "contract_address": _norm_lower(contract_address),
                }
            )
        )


class ProtocolFeeCollectorReporterRepositoryMongoDB:
    COLLECTION_NAME = "admin_protocol_fee_collector_reporters"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db if db is not None else get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("chain", 1), ("contract_address", 1), ("reporter", 1)],
            unique=True,
            name="ux_admin_protocol_fee_collector_reporters_unique",
        )
        self._collection.create_index(
            [("updated_at", -1)],
            name="ix_admin_protocol_fee_collector_reporters_updated_desc",
        )

    def upsert(
        self,
        *,
        chain: str,
        contract_address: str,
        reporter: str,
        desired_allowed: bool,
        tx_hash: str | None,
        updated_by: str | None,
    ) -> dict:
        ts, iso = _now_meta()

        flt = {
            "chain": _norm_lower(chain),
            "contract_address": _norm_lower(contract_address),
            "reporter": _norm_lower(reporter),
        }

        self._collection.update_one(
            flt,
            {
                "$set": {
                    "chain": _norm_lower(chain),
                    "contract_address": _norm_lower(contract_address),
                    "reporter": _norm_lower(reporter),
                    "desired_allowed": bool(desired_allowed),
                    "tx_hash": _norm_lower(tx_hash) if tx_hash else None,
                    "updated_by": _norm_lower(updated_by) if updated_by else None,
                    "updated_at": ts,
                    "updated_at_iso": iso,
                },
                "$setOnInsert": {
                    "created_at": ts,
                    "created_at_iso": iso,
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
        limit: int = 500,
    ) -> list[dict]:
        cursor = self._collection.find(
            {
                "chain": _norm_lower(chain),
                "contract_address": _norm_lower(contract_address),
            },
            sort=[("updated_at", -1), ("reporter", 1)],
        ).limit(int(limit))

        return [_serialize_doc(doc) for doc in cursor if doc]


class VaultFeeBufferDepositorRepositoryMongoDB:
    COLLECTION_NAME = "admin_vault_fee_buffer_depositors"

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db if db is not None else get_mongo_db()
        self._collection: Collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("chain", 1), ("contract_address", 1), ("depositor", 1)],
            unique=True,
            name="ux_admin_vault_fee_buffer_depositors_unique",
        )
        self._collection.create_index(
            [("updated_at", -1)],
            name="ix_admin_vault_fee_buffer_depositors_updated_desc",
        )

    def upsert(
        self,
        *,
        chain: str,
        contract_address: str,
        depositor: str,
        label: str | None,
        desired_allowed: bool,
        tx_hash: str | None,
        updated_by: str | None,
    ) -> dict:
        ts, iso = _now_meta()

        flt = {
            "chain": _norm_lower(chain),
            "contract_address": _norm_lower(contract_address),
            "depositor": _norm_lower(depositor),
        }

        self._collection.update_one(
            flt,
            {
                "$set": {
                    "chain": _norm_lower(chain),
                    "contract_address": _norm_lower(contract_address),
                    "depositor": _norm_lower(depositor),
                    "label": (label or "").strip() or None,
                    "desired_allowed": bool(desired_allowed),
                    "tx_hash": _norm_lower(tx_hash) if tx_hash else None,
                    "updated_by": _norm_lower(updated_by) if updated_by else None,
                    "updated_at": ts,
                    "updated_at_iso": iso,
                },
                "$setOnInsert": {
                    "created_at": ts,
                    "created_at_iso": iso,
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
        limit: int = 500,
    ) -> list[dict]:
        cursor = self._collection.find(
            {
                "chain": _norm_lower(chain),
                "contract_address": _norm_lower(contract_address),
            },
            sort=[("label", 1), ("updated_at", -1), ("depositor", 1)],
        ).limit(int(limit))

        return [_serialize_doc(doc) for doc in cursor if doc]