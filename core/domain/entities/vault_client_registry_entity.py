from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field

from .base_entity import MongoEntity


class SwapPoolRef(BaseModel):
    dex: str
    pool: str

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class HarvestJobConfig(BaseModel):
    """
    Optional defaults/config for harvest_job.
    The scheduler/job runner can read this from vault_registry and call the endpoint accordingly.
    """
    enabled: bool = True
    harvest_pool_fees: bool = True
    harvest_rewards: bool = True

    swap_rewards: bool = False
    reward_amount_in: int = 0
    reward_amount_out_min: int = 0
    reward_sqrt_price_limit_x96: int = 0

    gas_strategy: str = "buffered"

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class CompoundJobConfig(BaseModel):
    """
    Optional defaults/config for compound_job.
    The scheduler/job runner can read this from vault_registry and call the endpoint accordingly.
    """
    enabled: bool = True

    compound0_desired: int = 0
    compound1_desired: int = 0
    compound0_min: int = 0
    compound1_min: int = 0

    gas_strategy: str = "buffered"

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class VaultJobsConfig(BaseModel):
    """
    Container for job-related config stored inside vault_registry.
    """
    harvest_job: HarvestJobConfig = Field(default_factory=HarvestJobConfig)
    compound_job: CompoundJobConfig = Field(default_factory=CompoundJobConfig)

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class VaultConfig(BaseModel):
    address: str = Field(..., description="ClientVault deployed/created address")
    adapter: str
    pool: str
    nfpm: str
    gauge: Optional[str] = None

    rpc_url: str
    version: str

    swap_pools: Dict[str, SwapPoolRef] = Field(default_factory=dict)

    jobs: VaultJobsConfig = Field(default_factory=VaultJobsConfig)

    model_config = ConfigDict(extra="allow", use_enum_values=True)


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

    model_config = ConfigDict(extra="allow", use_enum_values=True)


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
