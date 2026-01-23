from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional


class AdapterRegistryPublicOut(BaseModel):
    chain: str
    address: str

    dex: str
    pool: str
    nfpm: str
    gauge: str

    token0: str
    token1: str
    pool_name: str
    fee_bps: str


class FactoryPublicOut(BaseModel):
    chain: str
    address: str


class ContractsRegistryOut(BaseModel):
    chain: str = Field(..., description='Chain key (e.g. "base", "bnb")')

    strategy_factory: FactoryPublicOut
    vault_factory: FactoryPublicOut

    protocol_fee_collector: FactoryPublicOut
    vault_fee_buffer: FactoryPublicOut
    
    adapters: List[AdapterRegistryPublicOut]
