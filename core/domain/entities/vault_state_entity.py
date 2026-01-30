from __future__ import annotations

from typing import Any, Dict

from pydantic import ConfigDict

from .base_entity import MongoEntity


class VaultStateDocument(MongoEntity):
    """
    Mongo document (collection: vault_state).

    One document per (dex, alias), holding the *current* aggregated state payload.

    - dex: DEX identifier
    - alias: vault alias
    - state: aggregated state dictionary
    - created_at/created_at_iso/updated_at/updated_at_iso: inherited timestamps
    """

    dex: str
    alias: str
    state: Dict[str, Any]

    model_config = ConfigDict(extra="allow")
