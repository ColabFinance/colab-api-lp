# core/domain/entities/base_entity.py
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ConfigDict

E = TypeVar("E", bound="MongoEntity")


class MongoEntity(BaseModel):
    """
    Base entity for Mongo-backed documents.

    Conventions:
    - MongoDB `_id` is mapped to `id` as a string.
    - Timestamps are stored in both milliseconds and ISO-8601 (UTC).
    - Extra fields are allowed to keep forward compatibility.
    """

    id: Optional[str] = None  # maps _id

    created_at: Optional[int] = None
    created_at_iso: Optional[str] = None
    updated_at: Optional[int] = None
    updated_at_iso: Optional[str] = None

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="allow",
        use_enum_values=True,
    )

    @staticmethod
    def now_ms() -> int:
        """
        Return current time in milliseconds.
        """
        return int(time.time() * 1000)

    @staticmethod
    def now_iso() -> str:
        """
        Return current time in ISO-8601 UTC format ending with 'Z'.
        """
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @classmethod
    def from_mongo(cls: Type[E], doc: Optional[dict[str, Any]]) -> Optional[E]:
        """
        Build an entity from a raw MongoDB document.
        """
        if not doc:
            return None

        data = dict(doc)

        if "_id" in data:
            data["id"] = str(data.pop("_id"))

        # If someone stored ObjectId-like values in any field, Pydantic will coerce where possible.
        return cls.model_validate(data)

    def to_mongo(self) -> dict[str, Any]:
        """
        Serialize this entity into a MongoDB-ready dictionary.

        Notes:
        - Includes `_id` only when `id` is present.
        - Excludes None fields.
        """
        data = self.model_dump(mode="python", exclude_none=True)

        if "id" in data:
            data["_id"] = data.pop("id")

        return data

    def touch_for_insert(self: E) -> E:
        now_ms = self.now_ms()
        now_iso = self.now_iso()

        if self.created_at is None:
            self.created_at = now_ms
        if self.created_at_iso is None:
            self.created_at_iso = now_iso

        self.updated_at = now_ms
        self.updated_at_iso = now_iso
        return self


    def touch_for_update(self: E) -> E:
        now_ms = self.now_ms()
        now_iso = self.now_iso()

        self.updated_at = now_ms
        self.updated_at_iso = now_iso
        return self