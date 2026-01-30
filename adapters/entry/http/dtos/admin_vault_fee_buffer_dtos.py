from pydantic import BaseModel, Field, field_validator
from web3 import Web3

from core.domain.enums.tx_enums import GasStrategy


class CreateVaultFeeBufferRequest(BaseModel):
    """
    Request payload to deploy a VaultFeeBuffer contract on-chain and persist it in MongoDB.
    """

    gas_strategy: GasStrategy = Field(default=GasStrategy.BUFFERED)
    chain: str = Field(..., description='Chain key (e.g. "base", "bnb")')

    initial_owner: str = Field(..., description="Owner of the contract (protocol multisig/admin).")

    @field_validator("initial_owner")
    @classmethod
    def _validate_owner(cls, v: str) -> str:
        v = (v or "").strip()
        if not Web3.is_address(v):
            raise ValueError("Invalid address in request (expected 0x...).")
        return Web3.to_checksum_address(v)

    @field_validator("chain")
    @classmethod
    def _validate_chain(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v:
            raise ValueError("chain is required")
        return v
