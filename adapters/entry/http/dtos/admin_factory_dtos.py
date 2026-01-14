from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional

from web3 import Web3


GasStrategy = Literal["default", "buffered", "aggressive"]


class CreateStrategyRegistryRequest(BaseModel):
    gas_strategy: GasStrategy = Field(default="buffered")
    chain: str = Field(..., description='Chain key (e.g. "base", "bnb")')
    initial_owner: str = Field(...)

    @field_validator("initial_owner")
    @classmethod
    def _validate_owner(cls, v: str) -> str:
        v = (v or "").strip()
        if not Web3.is_address(v):
            raise ValueError("initial_owner must be a valid EVM address (0x...).")
        return Web3.to_checksum_address(v)

class CreateVaultFactoryRequest(BaseModel):
    gas_strategy: GasStrategy = Field(default="buffered")
    chain: str = Field(..., description='Chain key (e.g. "base", "bnb")')
    initial_owner: str
    strategy_registry: str
    executor: str
    fee_collector: str = Field(default="0x0000000000000000000000000000000000000000")

    default_cooldown_sec: int = Field(default=300, ge=0)
    default_max_slippage_bps: int = Field(default=50, ge=0, le=10_000)
    default_allow_swap: bool = Field(default=True)

    @field_validator("initial_owner", "strategy_registry", "executor", "fee_collector")
    @classmethod
    def _validate_addresses(cls, v: str) -> str:
        v = (v or "").strip()
        if not Web3.is_address(v):
            raise ValueError("Invalid address in request (expected 0x...).")
        return Web3.to_checksum_address(v)


class FactoryRecordOut(BaseModel):
    chain: str
    address: str
    status: str
    created_at: str
    tx_hash: str | None = None
