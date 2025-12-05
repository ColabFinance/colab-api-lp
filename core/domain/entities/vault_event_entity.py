# domain/entities/vault_event_entity.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class VaultEvent:
    """
    Domain entity representing a single historical vault event.

    Events are stored as separate documents in the `vault_events` collection
    and represent actions or measurements such as:
    - strategy executions
    - fee collections
    - deposits / withdrawals
    - reward collections
    - error occurrences

    Attributes:
        id: Optional MongoDB internal identifier (_id).
        dex: DEX identifier (e.g. "uniswap", "aerodrome", "pancake").
        alias: Vault alias.
        kind: Event kind (e.g. "exec", "collect", "deposit", "error").
        ts: Integer timestamp in seconds.
        ts_iso: ISO-8601 string representation of the timestamp.
        payload: Arbitrary JSON-serializable dictionary with event details.
    """

    dex: str
    alias: str
    kind: str
    ts: int
    ts_iso: str
    payload: Dict[str, Any]
    id: Optional[Any] = None

    @classmethod
    def from_mongo(cls, doc: Dict[str, Any]) -> "VaultEvent":
        """
        Build a VaultEvent from a raw MongoDB document.
        """
        if not doc:
            raise ValueError("Cannot build VaultEvent from empty document")

        return cls(
            id=doc.get("_id"),
            dex=doc["dex"],
            alias=doc["alias"],
            kind=doc["kind"],
            ts=int(doc.get("ts", 0)),
            ts_iso=str(doc.get("ts_iso", "")),
            payload=doc.get("payload") or {},
        )

    def to_mongo(self) -> Dict[str, Any]:
        """
        Serialize this entity into a MongoDB-ready dictionary.

        The internal `_id` field is included only if present.
        """
        doc: Dict[str, Any] = {
            "dex": self.dex,
            "alias": self.alias,
            "kind": self.kind,
            "ts": self.ts,
            "ts_iso": self.ts_iso,
            "payload": self.payload,
        }
        if self.id is not None:
            doc["_id"] = self.id
        return doc
