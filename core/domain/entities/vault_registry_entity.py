# domain/entities/vault_registry_entity.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class VaultRegistryEntry:
    """
    Domain entity representing a single vault registry record.

    This corresponds to one row previously stored in `vaults.json` and now
    persisted as a document in the `vault_registry` collection.

    Attributes:
        id: Optional MongoDB internal identifier (_id), usually an ObjectId.
        dex: DEX identifier (e.g. "uniswap", "aerodrome", "pancake").
        alias: Logical vault alias (unique per DEX).
        config: Arbitrary configuration dictionary for this vault.
        is_active: Whether this vault is the active one for the given DEX.
        created_at: ISO-8601 string with the creation timestamp.
        updated_at: ISO-8601 string with the last update timestamp.
    """

    dex: str
    alias: str
    config: Dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: str
    id: Optional[Any] = None

    @classmethod
    def from_mongo(cls, doc: Dict[str, Any]) -> VaultRegistryEntry:
        """
        Build a VaultRegistryEntry from a raw MongoDB document.
        """
        if not doc:
            raise ValueError("Cannot build VaultRegistryEntry from empty document")

        return cls(
            id=doc.get("_id"),
            dex=doc["dex"],
            alias=doc["alias"],
            config=doc.get("config") or {},
            is_active=bool(doc.get("is_active", False)),
            created_at=str(doc.get("created_at", "")),
            updated_at=str(doc.get("updated_at", "")),
        )

    def to_mongo(self) -> Dict[str, Any]:
        """
        Serialize this entity into a MongoDB-ready dictionary.

        The internal `_id` field is included only if present.
        """
        doc: Dict[str, Any] = {
            "dex": self.dex,
            "alias": self.alias,
            "config": self.config,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.id is not None:
            doc["_id"] = self.id
        return doc
