from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List, Optional, Set

from pymongo.collection import Collection
from web3 import Web3

from core.domain.entities.vault_client_registry_entity import VaultRegistryEntity
from core.domain.repositories.vault_client_registry_repository_interface import VaultRegistryRepositoryInterface


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_iso() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _norm_slug(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    v = (s or "").strip().lower().replace(" ", "").replace("/", "-")
    return v or None


def _owner_variants(owner: str) -> List[str]:
    o = (owner or "").strip()
    if not o:
        return []
    vs: Set[str] = {o, o.lower()}
    if Web3.is_address(o):
        try:
            vs.add(Web3.to_checksum_address(o))
        except Exception:
            pass
    return list(vs)


class VaultRegistryRepositoryMongoDB(VaultRegistryRepositoryInterface):
    COLLECTION = "vault_registry"

    def __init__(self, col: Collection):
        self._col = col

    def ensure_indexes(self) -> None:
        # alias must be unique
        self._col.create_index([("alias", 1)], unique=True, name="ux_alias")
        self._col.create_index([("address", 1)], unique=True, name="ux_address")

        # helpful search indexes
        self._col.create_index([("chain", 1), ("dex", 1), ("owner", 1)], name="ix_chain_dex_owner")
        self._col.create_index([("created_at", -1)], name="ix_created_at_desc")

    def insert(self, entity: VaultRegistryEntity) -> VaultRegistryEntity:
        doc = entity.to_mongo()

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

    def find_by_address(self, address: str) -> Optional[VaultRegistryEntity]:
        doc = self._col.find_one({"address": address})
        return VaultRegistryEntity.from_mongo(doc)

    def count_alias_prefix(self, *, chain: str, dex: str, owner_prefix: str, par_token: str) -> int:
        prefix = f"{owner_prefix}-{par_token}-{dex}-{chain}-"
        return int(self._col.count_documents({"alias": {"$regex": f"^{prefix}"}}))

    def list_by_owner(
        self,
        *,
        owner: str,
        chain: Optional[str] = None,
        dex: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[VaultRegistryEntity]:
        owner_keys = _owner_variants(owner)
        if not owner_keys:
            return []

        q: dict = {"owner": {"$in": owner_keys}}

        chain_n = _norm_slug(chain)
        dex_n = _norm_slug(dex)

        if chain_n:
            q["chain"] = chain_n
        if dex_n:
            q["dex"] = dex_n

        cur = (
            self._col.find(q)
            .sort("created_at", -1)
            .skip(int(offset or 0))
            .limit(int(limit or 200))
        )
        docs = list(cur)
        return [VaultRegistryEntity.from_mongo(d) for d in docs if d]
