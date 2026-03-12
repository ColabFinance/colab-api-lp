from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict, Field

from core.domain.entities.base_entity import MongoEntity
from core.domain.enums.dex_registry_enums import DexRegistryStatus, DexPoolType


class DexRegistryEntity(MongoEntity):
    """
    Mongo document (collection: dex_registries).
    One record per (chain, dex).
    Stores global wiring like dex_router.
    """

    chain: str
    dex: str

    dex_router: str
    status: DexRegistryStatus = DexRegistryStatus.ACTIVE

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class DexPoolEntity(MongoEntity):
    """
    Mongo document (collection: dex_pools).
    One record per (chain, dex, pool).
    Stores pool-level wiring like nfpm/gauge/tokens/fee.
    Optionally stores adapter (deployed adapter contract address).
    """

    chain: str
    dex: str

    pool: str
    nfpm: str
    gauge: str = "0x0000000000000000000000000000000000000000"

    token0: str
    token1: str

    pair: str = Field(default="", description="Human label e.g. WETH-USDC")
    symbol: str = Field(default="", description="Human symbol e.g. ETHUSDT")

    fee_bps: int
    fee_rate: str

    adapter: Optional[str] = None

    status: DexRegistryStatus = DexRegistryStatus.ACTIVE

    reward_token: str = "0x0000000000000000000000000000000000000000"
    reward_swap_pool: str = "0x0000000000000000000000000000000000000000"

    pool_type: DexPoolType = DexPoolType.CONCENTRATED
    tick_spacing: Optional[int] = None

    model_config = ConfigDict(extra="allow", use_enum_values=True)