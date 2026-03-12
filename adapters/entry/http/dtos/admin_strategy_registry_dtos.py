from pydantic import BaseModel, Field, field_validator

from web3 import Web3

from core.domain.enums.tx_enums import GasStrategy


class CreateStrategyRegistryRequest(BaseModel):
    gas_strategy: GasStrategy = Field(default=GasStrategy.BUFFERED)
    chain: str = Field(..., description='Chain key (e.g. "base", "bnb")')
    initial_owner: str = Field(...)

    @field_validator("initial_owner")
    @classmethod
    def _validate_owner(cls, v: str) -> str:
        v = (v or "").strip()
        if not Web3.is_address(v):
            raise ValueError("initial_owner must be a valid EVM address (0x...).")
        return Web3.to_checksum_address(v)

class FactoryRecordOut(BaseModel):
    chain: str
    address: str
    status: str
    created_at: str
    tx_hash: str | None = None
