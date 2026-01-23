from pydantic import BaseModel, Field, field_validator
from web3 import Web3

from core.domain.enums.tx_enums import GasStrategy


class CreateProtocolFeeCollectorRequest(BaseModel):
    """
    Request payload to deploy a ProtocolFeeCollector contract on-chain and persist it in MongoDB.
    """

    gas_strategy: GasStrategy = Field(default=GasStrategy.BUFFERED)
    chain: str = Field(..., description='Chain key (e.g. "base", "bnb")')

    initial_owner: str = Field(..., description="Owner of the contract (e.g. multisig).")
    treasury: str = Field(..., description="Treasury address that receives withdrawals.")
    protocol_fee_bps: int = Field(..., ge=0, le=5000, description="Protocol fee in basis points (max 5000).")

    @field_validator("initial_owner", "treasury")
    @classmethod
    def _validate_addresses(cls, v: str) -> str:
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
