from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.domain.entities.vault_client_registry_entity import SwapPoolRef, VaultConfig


class VaultSwapPoolRefIn(BaseModel):
    """
    Input schema for swap pool references used by the status service.
    """
    dex: str = Field(..., description="DEX identifier (e.g. uniswap, aerodrome, pancake)")
    pool: str = Field(..., description="Pool address")

    model_config = ConfigDict(extra="ignore")

    def to_domain(self) -> SwapPoolRef:
        return SwapPoolRef(dex=self.dex, pool=self.pool)


class VaultCreateConfigIn(BaseModel):
    """
    Canonical input schema for vault creation config.

    This object is sent by the API, stored inside Mongo under `config`,
    and later used for on-chain reads (status) and routing.
    """
    adapter: str = Field(..., description="Adapter contract address")
    pool: str = Field(..., description="Pool address")
    nfpm: str = Field(..., description="NonfungiblePositionManager address")
    gauge: Optional[str] = Field(default=None, description="Gauge address (optional)")

    rpc_url: str = Field(..., description="RPC URL used by backend services")
    version: str = Field(..., description="Config version tag")

    swap_pools: Dict[str, VaultSwapPoolRefIn] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")

    def to_domain(self, *, address: str) -> VaultConfig:
        return VaultConfig(
            address=address,
            adapter=self.adapter,
            pool=self.pool,
            nfpm=self.nfpm,
            gauge=self.gauge,
            rpc_url=self.rpc_url,
            version=self.version,
            swap_pools={k: v.to_domain() for k, v in (self.swap_pools or {}).items()},
        )
