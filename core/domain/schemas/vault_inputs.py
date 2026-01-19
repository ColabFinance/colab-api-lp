from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, Field

from core.domain.entities.vault_client_registry_entity import SwapPoolRef


class VaultCreateConfigIn(BaseModel):
    adapter: str = ""
    pool: str = ""
    nfpm: str = ""
    gauge: Optional[str] = None
    rpc_url: str = ""
    version: str = ""
    swap_pools: Dict[str, SwapPoolRef] = Field(default_factory=dict)
