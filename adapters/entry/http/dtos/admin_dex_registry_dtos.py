from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator
from web3 import Web3

from core.domain.enums.dex_registry_enums import DexRegistryStatus


ZERO = "0x0000000000000000000000000000000000000000"


def _checksum(v: str) -> str:
    return Web3.to_checksum_address(v)


def _validate_addr(v: str, *, allow_zero: bool) -> str:
    v = (v or "").strip()
    if not Web3.is_address(v):
        raise ValueError("Invalid address (expected 0x...).")
    v = _checksum(v)
    if not allow_zero and v.lower() == ZERO.lower():
        raise ValueError("Address cannot be zero.")
    return v


class CreateDexRequest(BaseModel):
    chain: str = Field(..., description='Chain key (e.g. "base", "bnb")')
    dex: str = Field(..., description='DEX key (e.g. "pancake_v3", "uniswap_v3", "aerodrome")')
    dex_router: str = Field(..., description="DEX router used by ClientVault for swaps")
    status: DexRegistryStatus = Field(default=DexRegistryStatus.ACTIVE)

    @field_validator("chain", "dex")
    @classmethod
    def _norm_lower(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v:
            raise ValueError("Field is required.")
        return v

    @field_validator("dex_router")
    @classmethod
    def _addr_router(cls, v: str) -> str:
        return _validate_addr(v, allow_zero=False)


class CreateDexPoolRequest(BaseModel):
    chain: str
    dex: str

    pool: str
    nfpm: str
    gauge: str = Field(default=ZERO)

    token0: str
    token1: str

    pair: str = Field(default="")
    symbol: str = Field(default="")

    fee_bps: int = Field(..., ge=0, le=100_000)

    adapter: Optional[str] = Field(default=None, description="Optional deployed adapter address")
    reward_token: str
    
    status: DexRegistryStatus = Field(default=DexRegistryStatus.ACTIVE)

    @field_validator("chain", "dex")
    @classmethod
    def _norm_lower(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v:
            raise ValueError("Field is required.")
        return v

    @field_validator("pool", "nfpm", "token0", "token1")
    @classmethod
    def _addr_nonzero(cls, v: str) -> str:
        return _validate_addr(v, allow_zero=False)

    @field_validator("gauge")
    @classmethod
    def _addr_gauge(cls, v: str) -> str:
        return _validate_addr(v, allow_zero=True)

    @field_validator("adapter")
    @classmethod
    def _addr_adapter_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        vv = (v or "").strip()
        if not vv:
            return None
        return _validate_addr(vv, allow_zero=False)

    @field_validator("token1")
    @classmethod
    def _tokens_not_equal(cls, v: str, info) -> str:
        token0 = (info.data.get("token0") or "").lower()
        if token0 and token0 == (v or "").lower():
            raise ValueError("token0 and token1 cannot be the same.")
        return v
