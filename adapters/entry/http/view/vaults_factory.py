# adapters/entry/http/view/vaults_factory.py
from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.dtos.vaults_factory_dtos import CreateVaultTxRequest, FactoryConfigOut, SetDefaultsTxRequest, SetExecutorTxRequest, SetFeeCollectorTxRequest, TxEnvelopeResponse
from core.use_cases.vaults_factory_usecase import VaultFactoryUseCase

router = APIRouter(
    prefix="/vaults",
    tags=["vaults-factory"],
)


def get_use_case() -> VaultFactoryUseCase:
    """
    Dependency para criar o use case já com Web3 + adapters configurados.
    """
    return VaultFactoryUseCase.from_settings()

# ---------------------------------------------------------------------------
# VaultFactory endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/factory/config",
    response_model=FactoryConfigOut,
    summary="Ler config atual do VaultFactory (executor, defaults, feeCollector)",
)
async def get_factory_config(
    use_case: VaultFactoryUseCase = Depends(get_use_case),
):
    cfg = use_case.get_factory_config()
    return FactoryConfigOut(**cfg)


@router.post(
    "/factory/create-client-vault-tx",
    response_model=TxEnvelopeResponse,
    summary="Montar tx de createClientVault para o front assinar com a wallet (user)",
)
async def create_client_vault_tx(
    body: CreateVaultTxRequest,
    use_case: VaultFactoryUseCase = Depends(get_use_case),
):
    try:
        tx = use_case.build_create_vault_tx(
            strategy_id=body.strategy_id,
            user_wallet=body.user_wallet,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to build createClientVault tx: {exc}"
        ) from exc

    return TxEnvelopeResponse(
        to=tx["to"],
        data=tx["data"],
        value=int(tx.get("value", 0)),
        chain_id=use_case.w3.eth.chain_id,
    )


@router.post(
    "/factory/set-executor-tx",
    response_model=TxEnvelopeResponse,
    summary="Montar tx para VaultFactory.setExecutor (admin, onlyOwner)",
)
async def build_set_executor_tx(
    body: SetExecutorTxRequest,
    use_case: VaultFactoryUseCase = Depends(get_use_case),
):
    try:
        tx = use_case.build_set_executor_tx(
            admin_wallet=body.admin_wallet,
            new_executor=body.new_executor,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to build setExecutor tx: {exc}"
        ) from exc

    return TxEnvelopeResponse(
        to=tx["to"],
        data=tx["data"],
        value=int(tx.get("value", 0)),
        chain_id=use_case.w3.eth.chain_id,
    )


@router.post(
    "/factory/set-fee-collector-tx",
    response_model=TxEnvelopeResponse,
    summary="Montar tx para VaultFactory.setFeeCollector (admin, onlyOwner)",
)
async def build_set_fee_collector_tx(
    body: SetFeeCollectorTxRequest,
    use_case: VaultFactoryUseCase = Depends(get_use_case),
):
    try:
        tx = use_case.build_set_fee_collector_tx(
            admin_wallet=body.admin_wallet,
            new_collector=body.new_collector,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to build setFeeCollector tx: {exc}"
        ) from exc

    return TxEnvelopeResponse(
        to=tx["to"],
        data=tx["data"],
        value=int(tx.get("value", 0)),
        chain_id=use_case.w3.eth.chain_id,
    )


@router.post(
    "/factory/set-defaults-tx",
    response_model=TxEnvelopeResponse,
    summary="Montar tx para VaultFactory.setDefaults (admin, onlyOwner)",
)
async def build_set_defaults_tx(
    body: SetDefaultsTxRequest,
    use_case: VaultFactoryUseCase = Depends(get_use_case),
):
    try:
        tx = use_case.build_set_defaults_tx(
            admin_wallet=body.admin_wallet,
            cooldown_sec=body.cooldown_sec,
            max_slippage_bps=body.max_slippage_bps,
            allow_swap=body.allow_swap,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to build setDefaults tx: {exc}"
        ) from exc

    return TxEnvelopeResponse(
        to=tx["to"],
        data=tx["data"],
        value=int(tx.get("value", 0)),
        chain_id=use_case.w3.eth.chain_id,
    )
