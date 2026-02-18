# vault_client_registry_repository_mongodb.py

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database

from adapters.external.database.helper_repo import sanitize_for_mongo  # type: ignore
from adapters.external.database.mongo_client import get_mongo_db  # type: ignore
from core.domain.entities.vault_client_registry_entity import VaultRegistryEntity
from core.domain.repositories.vault_client_registry_repository_interface import VaultRegistryRepositoryInterface
from core.services.normalize import _norm_lower


class VaultRegistryRepositoryMongoDB(VaultRegistryRepositoryInterface):
    COLLECTION_NAME = "vault_registry"

    def __init__(self, db: Optional[Database] = None, col: Optional[Collection] = None) -> None:
        if col is not None:
            self._collection = col
            self._db = col.database
        else:
            self._db = db if db is not None else get_mongo_db()
            self._collection = self._db[self.COLLECTION_NAME]
        self.ensure_indexes()

    @property
    def collection(self) -> Collection:
        return self._collection

    def ensure_indexes(self) -> None:
        self._collection.create_index([("alias", 1)], unique=True, name="ux_alias")
        self._collection.create_index([("address", 1)], unique=True, name="ux_address")
        self._collection.create_index([("chain", 1), ("dex", 1), ("owner", 1)], name="ix_chain_dex_owner")
        self._collection.create_index([("created_at", -1)], name="ix_created_at_desc")

    def _norm_vault_doc(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        # top-level
        for k in ("chain", "dex", "alias", "address", "owner", "par_token", "name"):
            if k in doc and isinstance(doc.get(k), str):
                doc[k] = _norm_lower(doc.get(k))

        # config (nested)
        cfg = doc.get("config")
        if isinstance(cfg, dict):
            for k in ("address", "adapter", "pool", "nfpm", "gauge", "reward_swap_pool", "rpc_url", "version"):
                if k in cfg and isinstance(cfg.get(k), str):
                    # NOTE: rpc_url/version are not addresses but keeping consistent lower-storage for strings is fine
                    cfg[k] = _norm_lower(cfg.get(k))

            swap_pools = cfg.get("swap_pools")
            if isinstance(swap_pools, dict):
                for _name, ref in list(swap_pools.items()):
                    if not isinstance(ref, dict):
                        continue
                    if isinstance(ref.get("dex"), str):
                        ref["dex"] = _norm_lower(ref.get("dex"))
                    if isinstance(ref.get("pool"), str):
                        ref["pool"] = _norm_lower(ref.get("pool"))

            cfg_jobs = cfg.get("jobs")
            if isinstance(cfg_jobs, dict):
                # keep as-is (booleans/ints), but normalize any stray strings (defensive)
                for job_k, job_v in cfg_jobs.items():
                    if isinstance(job_v, dict):
                        for kk, vv in list(job_v.items()):
                            if isinstance(vv, str):
                                job_v[kk] = _norm_lower(vv)

            doc["config"] = cfg

        # onchain (nested)
        onchain = doc.get("onchain")
        if isinstance(onchain, dict):
            for k in (
                "vault",
                "owner",
                "executor",
                "adapter",
                "dex_router",
                "fee_collector",
                "pool",
                "nfpm",
                "gauge",
            ):
                if k in onchain and isinstance(onchain.get(k), str):
                    onchain[k] = _norm_lower(onchain.get(k))
            doc["onchain"] = onchain

        return doc

    def insert(self, entity: VaultRegistryEntity) -> VaultRegistryEntity:
        entity = entity.touch_for_insert()
        doc = sanitize_for_mongo(entity.to_mongo())
        doc = self._norm_vault_doc(doc)

        res = self._collection.insert_one(doc)
        saved = dict(doc)
        saved["_id"] = res.inserted_id
        return VaultRegistryEntity.from_mongo(saved)

    def find_by_alias(self, alias: str) -> Optional[VaultRegistryEntity]:
        doc = self._collection.find_one({"alias": _norm_lower(alias)})
        return VaultRegistryEntity.from_mongo(doc)

    def find_by_address(self, address: str) -> Optional[VaultRegistryEntity]:
        doc = self._collection.find_one({"address": _norm_lower(address)})
        return VaultRegistryEntity.from_mongo(doc)

    def count_alias_prefix(self, *, chain: str, dex: str, owner_prefix: str, par_token: str) -> int:
        prefix = f"{_norm_lower(owner_prefix)}-{_norm_lower(par_token)}-{_norm_lower(dex)}-{_norm_lower(chain)}-"
        return int(self._collection.count_documents({"alias": {"$regex": f"^{prefix}"}}))

    def list_by_owner(
        self,
        *,
        owner: str,
        chain: Optional[str] = None,
        dex: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[VaultRegistryEntity]:
        owner_n = _norm_lower(owner)
        if not owner_n:
            return []

        q: Dict[str, Any] = {"owner": owner_n}

        if chain:
            q["chain"] = _norm_lower(chain)
        if dex:
            q["dex"] = _norm_lower(dex)

        cur = (
            self._collection.find(q)
            .sort("created_at", -1)
            .skip(int(offset or 0))
            .limit(int(limit or 200))
        )
        docs = list(cur)
        return [VaultRegistryEntity.from_mongo(d) for d in docs if d]

    def update_fields(self, *, address: str, set_fields: Dict[str, Any]) -> VaultRegistryEntity:
        addr_n = _norm_lower(address)
        if not (isinstance(addr_n, str) and addr_n.startswith("0x") and len(addr_n) == 42):
            raise ValueError("Invalid address for update_fields")

        set_doc = sanitize_for_mongo(dict(set_fields or {}))

        # normalize known fields (top-level + config.* when provided)
        for k in ("chain", "dex", "alias", "address", "owner", "par_token", "name"):
            if k in set_doc and isinstance(set_doc.get(k), str):
                set_doc[k] = _norm_lower(set_doc.get(k))

        if isinstance(set_doc.get("config"), dict):
            cfg = dict(set_doc["config"])
            for k in ("address", "adapter", "pool", "nfpm", "gauge", "reward_swap_pool", "rpc_url", "version"):
                if k in cfg and isinstance(cfg.get(k), str):
                    cfg[k] = _norm_lower(cfg.get(k))
            if isinstance(cfg.get("swap_pools"), dict):
                for _name, ref in list(cfg["swap_pools"].items()):
                    if not isinstance(ref, dict):
                        continue
                    if isinstance(ref.get("dex"), str):
                        ref["dex"] = _norm_lower(ref.get("dex"))
                    if isinstance(ref.get("pool"), str):
                        ref["pool"] = _norm_lower(ref.get("pool"))
            set_doc["config"] = cfg

        # touch timestamps (ms/iso) consistently with entity base
        now_ms = VaultRegistryEntity.now_ms()
        now_iso = VaultRegistryEntity.now_iso()
        set_doc["updated_at"] = now_ms
        set_doc["updated_at_iso"] = now_iso

        updated = self._collection.find_one_and_update(
            {"address": addr_n},
            {"$set": set_doc},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            raise ValueError("Vault not found for update")

        return VaultRegistryEntity.from_mongo(updated)
