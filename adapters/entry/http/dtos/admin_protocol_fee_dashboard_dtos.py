from pydantic import BaseModel, Field, field_validator
from web3 import Web3


def _validate_address(v: str) -> str:
    v = (v or "").strip()
    if not Web3.is_address(v):
        raise ValueError("Invalid address in request (expected 0x...).")
    return Web3.to_checksum_address(v)


class BaseProtocolFeeDashboardRequest(BaseModel):
    chain: str = Field(..., description='Chain key (e.g. "base", "bnb")')
    contract_address: str | None = Field(default=None)

    @field_validator("chain")
    @classmethod
    def _validate_chain(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v:
            raise ValueError("chain is required")
        return v

    @field_validator("contract_address")
    @classmethod
    def _validate_contract_address(cls, v: str | None) -> str | None:
        if not v:
            return None
        return _validate_address(v)


class TrackProtocolFeeTokenRequest(BaseProtocolFeeDashboardRequest):
    token_address: str
    label: str | None = None

    @field_validator("token_address")
    @classmethod
    def _validate_token_address(cls, v: str) -> str:
        return _validate_address(v)


class RecordProtocolFeeWithdrawalRequest(BaseProtocolFeeDashboardRequest):
    tx_hash: str
    token_address: str
    token_symbol: str | None = None
    amount_raw: str
    amount_label: str | None = None
    destination: str
    status: str = Field(default="success")

    @field_validator("token_address", "destination")
    @classmethod
    def _validate_addresses(cls, v: str) -> str:
        return _validate_address(v)

    @field_validator("tx_hash")
    @classmethod
    def _validate_tx_hash(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v.startswith("0x") or len(v) < 10:
            raise ValueError("tx_hash is invalid.")
        return v

    @field_validator("amount_raw")
    @classmethod
    def _validate_amount_raw(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.isdigit():
            raise ValueError("amount_raw must be a numeric string.")
        if int(v) <= 0:
            raise ValueError("amount_raw must be > 0.")
        return v

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in {"success", "pending", "failed"}:
            raise ValueError("status must be success, pending, or failed.")
        return v