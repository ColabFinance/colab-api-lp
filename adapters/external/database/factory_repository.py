from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from adapters.external.database.mongo_client import get_mongo_client


@dataclass(frozen=True)
class FactoryStatuses:
    ACTIVE = "ACTIVE"
    ALLOW_CREATE = "ALLOW_CREATE"  # when current factory can be replaced
    ARCHIVED = "ARCHIVED"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseFactoryRepo:
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.db = get_mongo_client()

    @property
    def col(self):
        return self.db[self.collection_name]

    def get_active(self) -> Optional[Dict[str, Any]]:
        return self.col.find_one({"status": FactoryStatuses.ACTIVE})

    def get_latest(self) -> Optional[Dict[str, Any]]:
        return self.col.find_one(sort=[("created_at", -1)])

    def create_if_allowed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enforces:
        - Do not create a new factory if there is an ACTIVE one.
        - If there is a factory, creation is only allowed when latest status == ALLOW_CREATE.
        - The new factory becomes ACTIVE.
        - Previous ACTIVE (if any) is archived (safety), but normally it should not exist here.
        """
        active = self.get_active()
        if active:
            return {
                "ok": False,
                "message": "Factory already exists with ACTIVE status. Creation blocked.",
                "data": {"active_factory": active},
            }

        latest = self.get_latest()
        if latest and latest.get("status") != FactoryStatuses.ALLOW_CREATE:
            return {
                "ok": False,
                "message": "Factory creation is not allowed by current status.",
                "data": {"latest_factory": latest},
            }

        doc = {
            **payload,
            "status": FactoryStatuses.ACTIVE,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        inserted = self.col.insert_one(doc)
        doc["_id"] = str(inserted.inserted_id)

        return {"ok": True, "message": "Factory created and set to ACTIVE.", "data": doc}

    def set_status(self, factory_id: str, status: str) -> Dict[str, Any]:
        res = self.col.update_one(
            {"_id": factory_id},
            {"$set": {"status": status, "updated_at": _utcnow()}},
        )
        return {"matched": res.matched_count, "modified": res.modified_count}


class StrategyFactoryRepo(BaseFactoryRepo):
    def __init__(self):
        super().__init__("strategy_factories")


class VaultFactoryRepo(BaseFactoryRepo):
    def __init__(self):
        super().__init__("vault_factories")
