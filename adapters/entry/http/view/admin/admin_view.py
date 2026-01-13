from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.view.admin.admin_auth import require_admin, AdminPrincipal
from adapters.entry.http.dtos.admin_factory_dtos import (
    CreateStrategyRegistryRequest,
    CreateVaultFactoryRequest,
)
from core.use_cases.admin_factories_usecase import AdminFactoriesUseCase
from core.services.exceptions import TransactionRevertedError

router = APIRouter(prefix="/admin", tags=["admin"])


def get_use_case() -> AdminFactoriesUseCase:
    return AdminFactoriesUseCase.from_settings()


@router.post("/strategy-registry/create")
async def create_strategy_factory(
    body: CreateStrategyRegistryRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminFactoriesUseCase = Depends(get_use_case),
):
    try:
        initial_owner = (body.initial_owner or admin.wallet_address or "").strip()
        return use_case.create_strategy_registry(
            initial_owner=initial_owner,
            gas_strategy=body.gas_strategy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransactionRevertedError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt},
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create strategy factory: {exc}") from exc


@router.post("/vault-factory/create")
async def create_vault_factory(
    body: CreateVaultFactoryRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminFactoriesUseCase = Depends(get_use_case),
):
    try:
        initial_owner = (body.initial_owner or admin.wallet_address or "").strip()
        return use_case.create_vault_factory(
            initial_owner=initial_owner,
            strategy_registry=body.strategy_registry,
            executor=body.executor,
            fee_collector=body.fee_collector,
            default_cooldown_sec=body.default_cooldown_sec,
            default_max_slippage_bps=body.default_max_slippage_bps,
            default_allow_swap=body.default_allow_swap,
            gas_strategy=body.gas_strategy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransactionRevertedError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt},
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create vault factory: {exc}") from exc
