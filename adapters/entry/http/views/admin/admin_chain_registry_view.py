from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from adapters.entry.http.dtos.admin_chain_registry_dtos import CreateChainRequest, UpdateChainRequest
from adapters.entry.http.views.admin.admin_auth import AdminPrincipal, require_admin

from core.use_cases.admin_chain_registry_usecase import AdminChainRegistryUseCase


router = APIRouter(prefix="/admin", tags=["admin"])


def get_use_case() -> AdminChainRegistryUseCase:
    return AdminChainRegistryUseCase.from_settings()


@router.post("/chains/create")
async def create_chain_registry(
    body: CreateChainRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminChainRegistryUseCase = Depends(get_use_case),
):
    try:
        return use_case.create_chain(
            name=body.name,
            chain_id=body.chain_id,
            native_symbol=body.native_symbol,
            rpc_url=body.rpc_url,
            explorer_url=body.explorer_url,
            explorer_label=body.explorer_label,
            stables=body.stables,
            status=body.status,
            logo_url=body.logo_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create chain registry: {exc}") from exc


@router.get("/chains")
async def list_chain_registries(
    limit: int = Query(500, ge=1, le=5000),
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminChainRegistryUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_chains(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list chain registries: {exc}") from exc


@router.post("/chains/update")
async def update_chain_registry(
    body: UpdateChainRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminChainRegistryUseCase = Depends(get_use_case),
):
    try:
        return use_case.update_chain(
            key=body.key,
            name=body.name,
            chain_id=body.chain_id,
            native_symbol=body.native_symbol,
            rpc_url=body.rpc_url,
            explorer_url=body.explorer_url,
            explorer_label=body.explorer_label,
            stables=body.stables,
            status=body.status,
            logo_url=body.logo_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update chain registry: {exc}") from exc