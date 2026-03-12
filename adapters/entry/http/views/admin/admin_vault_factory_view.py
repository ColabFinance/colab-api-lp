from fastapi import APIRouter, Depends, HTTPException, Query

from adapters.entry.http.dtos.admin_vault_factory_dtos import CreateVaultFactoryRequest
from adapters.entry.http.views.admin.admin_auth import require_admin, AdminPrincipal

from core.services.exceptions import TransactionRevertedError
from core.use_cases.admin_vault_factory_usecase import AdminVaultFactoryUseCase

router = APIRouter(prefix="/admin", tags=["admin"])


def get_use_case() -> AdminVaultFactoryUseCase:
    return AdminVaultFactoryUseCase.from_settings()


@router.post("/vault-factory/create")
async def create_vault_factory(
    body: CreateVaultFactoryRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminVaultFactoryUseCase = Depends(get_use_case),
):
    try:
        initial_owner = (body.initial_owner or admin.wallet_address or "").strip()
        return use_case.create_vault_factory(
            chain=body.chain,
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


@router.get("/vault-factory")
async def list_vault_factories(
    chain: str = Query(..., description='Chain key (e.g. "base", "bnb")'),
    limit: int = Query(50, ge=1, le=200),
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminVaultFactoryUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_vault_factories(chain=chain, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list vault factories: {exc}") from exc