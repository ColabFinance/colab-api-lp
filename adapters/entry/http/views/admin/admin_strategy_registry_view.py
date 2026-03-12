from fastapi import APIRouter, Depends, HTTPException, Query

from adapters.entry.http.dtos.admin_strategy_registry_dtos import CreateStrategyRegistryRequest
from adapters.entry.http.views.admin.admin_auth import require_admin, AdminPrincipal
from core.services.exceptions import TransactionRevertedError
from core.use_cases.admin_strategy_registry_usecase import AdminStrategyFactoryUseCase

router = APIRouter(prefix="/admin", tags=["admin"])


def get_use_case() -> AdminStrategyFactoryUseCase:
    return AdminStrategyFactoryUseCase.from_settings()


@router.post("/strategy-registry/create")
async def create_strategy_factory(
    body: CreateStrategyRegistryRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminStrategyFactoryUseCase = Depends(get_use_case),
):
    try:
        initial_owner = (body.initial_owner or admin.wallet_address or "").strip()
        return use_case.create_strategy_registry(
            chain=body.chain,
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
        raise HTTPException(status_code=500, detail=f"Failed to create strategy registry: {exc}") from exc


@router.get("/strategy-registry")
async def list_strategy_registries(
    chain: str = Query(..., description='Chain key (e.g. "base", "bnb")'),
    limit: int = Query(50, ge=1, le=200),
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminStrategyFactoryUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_strategy_registries(chain=chain, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list strategy registries: {exc}") from exc