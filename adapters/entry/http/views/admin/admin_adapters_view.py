from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.views.admin.admin_auth import require_admin, AdminPrincipal
from adapters.entry.http.dtos.admin_adapter_dtos import CreateAdapterRequest
from core.use_cases.admin_adapters_usecase import AdminAdaptersUseCase
from core.services.exceptions import TransactionRevertedError

router = APIRouter(prefix="/admin", tags=["admin"])


def get_use_case() -> AdminAdaptersUseCase:
    return AdminAdaptersUseCase.from_settings()


@router.post("/adapters/create")
async def create_adapter(
    body: CreateAdapterRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminAdaptersUseCase = Depends(get_use_case),
):
    """
    Deploy a new adapter contract and persist its registry record in MongoDB.

    Notes:
      - Uniqueness is enforced by (dex, pool).
      - The deployed contract address is persisted as `address`.
      - All validation must be server-side (frontend is convenience-only).
    """
    try:
        created_by = (admin.wallet_address or "").strip() or None
        return use_case.create_adapter(
            dex=body.dex,
            pool=body.pool,
            nfpm=body.nfpm,
            gauge=body.gauge,
            token0=body.token0,
            token1=body.token1,
            pool_name=body.pool_name,
            fee_bps=body.fee_bps,
            status=body.status,
            created_by=created_by,
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
        raise HTTPException(status_code=500, detail=f"Failed to create adapter: {exc}") from exc


@router.get("/adapters")
async def list_adapters(
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminAdaptersUseCase = Depends(get_use_case),
):
    try:
        return {"ok": True, "message": "ok", "data": use_case.list_adapters(limit=200)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list adapters: {exc}") from exc
