# domain/entities/vault_state_entity.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class VaultStateDocument:
    """
    Domain entity representing the current state document of a vault.

    This corresponds to one document in the `vault_state` collection and
    wraps the `state` payload that holds the short, aggregated state.

    Attributes:
        id: Optional MongoDB internal identifier (_id).
        dex: DEX identifier.
        alias: Vault alias.
        state: Dictionary containing the current state payload.
        created_at: ISO-8601 string with the creation timestamp.
        updated_at: ISO-8601 string with the last update timestamp.
    """

    dex: str
    alias: str
    state: Dict[str, Any]
    created_at: str
    updated_at: str
    id: Optional[Any] = None

    @classmethod
    def from_mongo(cls, doc: Dict[str, Any]) -> "VaultStateDocument":
        """
        Build a VaultStateDocument from a raw MongoDB document.
        """
        if not doc:
            raise ValueError("Cannot build VaultStateDocument from empty document")

        return cls(
            id=doc.get("_id"),
            dex=doc["dex"],
            alias=doc["alias"],
            state=doc.get("state") or {},
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
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.id is not None:
            doc["_id"] = self.id
        return doc
