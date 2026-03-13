from pydantic import BaseModel, Field, field_validator
from web3 import Web3


def _validate_address(v: str) -> str:
    v = (v or "").strip()
    if not Web3.is_address(v):
        raise ValueError("Invalid address in request (expected 0x...).")
    return Web3.to_checksum_address(v)


class BaseChainRequest(BaseModel):
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


class SaveStrategyRouterStateRequest(BaseChainRequest):
    address: str
    name: str
    allowed: bool = True
    tx_hash: str | None = None

    @field_validator("address")
    @classmethod
    def _validate_address_field(cls, v: str) -> str:
        return _validate_address(v)


class SaveStrategyAdapterStateRequest(BaseChainRequest):
    address: str
    label: str
    adapter_type: str | None = None
    allowed: bool = True
    tx_hash: str | None = None

    @field_validator("address")
    @classmethod
    def _validate_address_field(cls, v: str) -> str:
        return _validate_address(v)


class SaveVaultFactoryStateRequest(BaseChainRequest):
    executor: str
    fee_collector: str
    default_cooldown_sec: int = Field(..., ge=0)
    default_max_slippage_bps: int = Field(..., ge=0, le=10_000)
    default_allow_swap: bool
    tx_hash: str | None = None

    @field_validator("executor", "fee_collector")
    @classmethod
    def _validate_addresses(cls, v: str) -> str:
        return _validate_address(v)


class SaveProtocolFeeCollectorStateRequest(BaseChainRequest):
    treasury: str
    protocol_fee_bps: int = Field(..., ge=0, le=5000)
    tx_hash: str | None = None

    @field_validator("treasury")
    @classmethod
    def _validate_treasury(cls, v: str) -> str:
        return _validate_address(v)


class SaveProtocolFeeReporterStateRequest(BaseChainRequest):
    reporter: str
    allowed: bool = True
    tx_hash: str | None = None

    @field_validator("reporter")
    @classmethod
    def _validate_reporter(cls, v: str) -> str:
        return _validate_address(v)


class SaveVaultFeeBufferDepositorStateRequest(BaseChainRequest):
    depositor: str
    label: str | None = None
    allowed: bool = True
    tx_hash: str | None = None

    @field_validator("depositor")
    @classmethod
    def _validate_depositor(cls, v: str) -> str:
        return _validate_address(v)