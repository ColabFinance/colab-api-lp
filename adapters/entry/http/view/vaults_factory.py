# adapters/entry/http/view/vaults_factory.py
from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.dtos.vaults_factory_dtos import (
    CreateClientVaultRequest,
    FactoryConfigOut,
    SetDefaultsRequest,
    SetExecutorRequest,
    SetFeeCollectorRequest,
    TxRunResponse,
)
from core.use_cases.vaults_factory_usecase import VaultFactoryUseCase
from core.services.exceptions import TransactionRevertedError

router = APIRouter(prefix="/vaults", tags=["vaults-factory"])


def get_use_case() -> VaultFactoryUseCase:
    return VaultFactoryUseCase.from_settings()


@router.get(
    "/admin/factory/config",
    response_model=FactoryConfigOut,
    summary="Ler config atual do VaultFactory (executor, defaults, feeCollector)",
)
async def get_factory_config(use_case: VaultFactoryUseCase = Depends(get_use_case)):
    cfg = use_case.get_factory_config()
    return FactoryConfigOut(**cfg)


@router.post(
    "/admin/factory/set-executor",
    response_model=TxRunResponse,
    summary="Executa setExecutor (onlyOwner, assinando no backend PK)",
)
async def set_executor(
    body: SetExecutorRequest,
    use_case: VaultFactoryUseCase = Depends(get_use_case),
):
    try:
        res = use_case.set_executor(new_executor=body.new_executor, gas_strategy=body.gas_strategy)
        return TxRunResponse(**res)
    except TransactionRevertedError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt},
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to setExecutor: {exc}") from exc


@router.post(
    "/admin/factory/set-fee-collector",
    response_model=TxRunResponse,
    summary="Executa setFeeCollector (onlyOwner, assinando no backend PK)",
)
async def set_fee_collector(
    body: SetFeeCollectorRequest,
    use_case: VaultFactoryUseCase = Depends(get_use_case),
):
    try:
        res = use_case.set_fee_collector(new_collector=body.new_collector, gas_strategy=body.gas_strategy)
        return TxRunResponse(**res)
    except TransactionRevertedError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt},
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to setFeeCollector: {exc}") from exc


@router.post(
    "/admin/factory/set-defaults",
    response_model=TxRunResponse,
    summary="Executa setDefaults (onlyOwner, assinando no backend PK)",
)
async def set_defaults(
    body: SetDefaultsRequest,
    use_case: VaultFactoryUseCase = Depends(get_use_case),
):
    try:
        res = use_case.set_defaults(
            cooldown_sec=body.cooldown_sec,
            max_slippage_bps=body.max_slippage_bps,
            allow_swap=body.allow_swap,
            gas_strategy=body.gas_strategy,
        )
        return TxRunResponse(**res)
    except TransactionRevertedError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt},
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to setDefaults: {exc}") from exc
