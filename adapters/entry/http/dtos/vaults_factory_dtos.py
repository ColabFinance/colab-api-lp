from pydantic import BaseModel, Field


class TxEnvelopeResponse(BaseModel):
    """
    Envelope genérico para tx EVM:
    - to, data, value, chain_id
    """

    to: str
    data: str
    value: int
    chain_id: int


class CreateVaultTxRequest(BaseModel):
    strategy_id: int = Field(..., ge=1)
    user_wallet: str = Field(
        ...,
        description="EOA do usuário (quem vai assinar a tx de createClientVault).",
    )


class SetExecutorTxRequest(BaseModel):
    admin_wallet: str
    new_executor: str


class SetFeeCollectorTxRequest(BaseModel):
    admin_wallet: str
    new_collector: str


class SetDefaultsTxRequest(BaseModel):
    admin_wallet: str
    cooldown_sec: int = Field(..., ge=0)
    max_slippage_bps: int = Field(..., ge=0, le=10_000)
    allow_swap: bool


class FactoryConfigOut(BaseModel):
    executor: str
    feeCollector: str
    defaultCooldownSec: int
    defaultMaxSlippageBps: int
    defaultAllowSwap: bool
