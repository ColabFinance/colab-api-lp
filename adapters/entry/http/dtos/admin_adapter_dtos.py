from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from typing import Literal

from web3 import Web3

from core.domain.enums.tx_enums import GasStrategy


class CreateAdapterRequest(BaseModel):
    """
    Admin request to deploy an adapter contract and persist the record in MongoDB.

    NOTE:
      - This endpoint performs an on-chain deployment.
      - The deployed contract address is derived from the transaction receipt,
        and persisted as `address` in MongoDB.
    """
    gas_strategy: GasStrategy = Field(default=GasStrategy.BUFFERED)

    chain: str = Field(..., description='Chain key (e.g. "base", "bnb")')
    
    dex: str = Field(..., description='DEX id (e.g. "pancake_v3")')

    # Contract constructor params (required)
    pool: str
    nfpm: str
    gauge: str  # may be zero address

    # Mongo metadata (not part of the contract)
    token0: str
    token1: str
    pool_name: str
    fee_bps: str
    status: str = Field(default="ACTIVE")

    @field_validator("pool", "nfpm", "gauge", "token0", "token1")
    @classmethod
    def _validate_addresses(cls, v: str) -> str:
        v = (v or "").strip()
        if not Web3.is_address(v):
            raise ValueError("Invalid address in request (expected 0x...).")
        return Web3.to_checksum_address(v)

    @field_validator("dex")
    @classmethod
    def _validate_dex(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("dex is required")
        if len(v) > 32:
            raise ValueError("dex too long")
        return v


class AdapterRecordOut(BaseModel):
    chain: str
    
    address: str
    tx_hash: str | None = None

    dex: str
    pool: str
    nfpm: str
    gauge: str

    token0: str
    token1: str
    pool_name: str
    fee_bps: str
    status: str

    created_at: str
    created_by: str | None = None
