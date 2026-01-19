from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import ConfigDict

from .base_entity import MongoEntity


class VaultEvent(MongoEntity):
    """
    Mongo document (collection: vault_events).

    One document per event:
    - dex: DEX identifier (e.g. "uniswap", "aerodrome", "pancake")
    - alias: vault alias
    - kind: event kind (e.g. "exec", "collect", "deposit", "error", "rewards_collect")
    - ts: integer timestamp in seconds
    - ts_iso: ISO-8601 string (UTC) for the timestamp
    - payload: arbitrary JSON payload with event details
    """

    dex: str
    alias: str
    kind: str

    ts: int
    ts_iso: str
    payload: Dict[str, Any]

    model_config = ConfigDict(extra="allow")
