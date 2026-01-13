from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.view.admin.admin_auth import require_admin, AdminPrincipal
from adapters.entry.http.dtos.admin_factory_dtos import CreateFactoryRequest, FactoryRecordOut
from core.use_cases.admin_factories_usecase import AdminFactoriesUseCase
from core.services.exceptions import TransactionRevertedError

router = APIRouter(prefix="/admin", tags=["admin"])


def get_use_case() -> AdminFactoriesUseCase:
    return AdminFactoriesUseCase.from_settings()


@router.post("/strategy-factory/create")
async def create_strategy_factory(
    body: CreateFactoryRequest,
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminFactoriesUseCase = Depends(get_use_case),
):
    try:
        return use_case.create_strategy_factory(gas_strategy=body.gas_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransactionRevertedError as exc:
        raise HTTPException(status_code=500, detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create strategy factory: {exc}") from exc


@router.post("/vault-factory/create")
async def create_vault_factory(
    body: CreateFactoryRequest,
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminFactoriesUseCase = Depends(get_use_case),
):
    try:
        return use_case.create_vault_factory(gas_strategy=body.gas_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransactionRevertedError as exc:
        raise HTTPException(status_code=500, detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create vault factory: {exc}") from exc


@router.get("/strategy-factory/list", response_model=list[FactoryRecordOut])
async def list_strategy_factories(
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminFactoriesUseCase = Depends(get_use_case),
):
    return use_case.list_strategy_factories(limit=50)


@router.get("/vault-factory/list", response_model=list[FactoryRecordOut])
async def list_vault_factories(
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminFactoriesUseCase = Depends(get_use_case),
):
    return use_case.list_vault_factories(limit=50)
