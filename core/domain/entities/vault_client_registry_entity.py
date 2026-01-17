# core/domain/entities/vault_registry_entity.py

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field

from .base_entity import MongoEntity


class SwapPoolRef(BaseModel):
    dex: str
    pool: str

    model_config = ConfigDict(extra="ignore")


class VaultConfig(BaseModel):
    address: str = Field(..., description="ClientVault deployed/created address")
    adapter: str
    pool: str
    nfpm: str
    gauge: Optional[str] = None

    rpc_url: str
    version: str

    swap_pools: Dict[str, SwapPoolRef] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class VaultOnchainInfo(BaseModel):
    """
    Snapshot of on-chain read-only information after create.
    Keep it flexible (extra allow) because status schema may evolve.
    """
    vault: str

    owner: Optional[str] = None
    executor: Optional[str] = None
    adapter: Optional[str] = None
    dex_router: Optional[str] = None
    fee_collector: Optional[str] = None
    strategy_id: Optional[int] = None

    pool: Optional[str] = None
    nfpm: Optional[str] = None
    gauge: Optional[str] = None

    token0: Optional[Dict[str, Any]] = None
    token1: Optional[Dict[str, Any]] = None

    position_token_id: Optional[int] = None
    liquidity: Optional[int] = None
    lower_tick: Optional[int] = None
    upper_tick: Optional[int] = None
    tick_spacing: Optional[int] = None

    tick: Optional[int] = None
    sqrt_price_x96: Optional[int] = None
    prices: Optional[Dict[str, Any]] = None

    out_of_range: Optional[bool] = None
    range_side: Optional[str] = None

    holdings: Optional[Dict[str, Any]] = None
    fees_uncollected: Optional[Dict[str, Any]] = None
    last_rebalance_ts: Optional[int] = None

    model_config = ConfigDict(extra="allow")


class VaultRegistryEntity(MongoEntity):
    """
    Canonical representation of documents in `vault_registry`.

    Required compatibility with existing structure:
      {
        dex: str,
        alias: str,
        config: {...},
        is_active: bool,
        created_at_iso, updated_at_iso, ...
      }

    Extended (new):
      chain, owner, par_token, name, description, strategy_id, onchain
    """

    dex: str
    alias: str
    address: str
    config: VaultConfig

    is_active: bool = False

    # new fields
    chain: str
    owner: str
    par_token: str

    name: str
    description: Optional[str] = None

    strategy_id: int

    model_config = ConfigDict(
        extra="allow",
        use_enum_values=True,
    )
