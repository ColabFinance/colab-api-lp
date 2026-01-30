from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from adapters.entry.http.views.admin.admin_auth import require_admin, AdminPrincipal
from adapters.entry.http.dtos.admin_dex_registry_dtos import CreateDexRequest, CreateDexPoolRequest

from core.use_cases.admin_dex_registry_usecase import AdminDexRegistryUseCase


router = APIRouter(prefix="/admin", tags=["admin"])


def get_use_case() -> AdminDexRegistryUseCase:
    return AdminDexRegistryUseCase.from_settings()


@router.post("/dexes/create")
async def create_dex_registry(
    body: CreateDexRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminDexRegistryUseCase = Depends(get_use_case),
):
    try:
        return use_case.create_dex(
            chain=body.chain,
            dex=body.dex,
            dex_router=body.dex_router,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create dex registry: {exc}") from exc


@router.get("/dexes")
async def list_dex_registries(
    chain: str = Query(..., description='Chain key (e.g. "base", "bnb")'),
    limit: int = Query(200, ge=1, le=1000),
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminDexRegistryUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_dexes(chain=chain, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list dex registries: {exc}") from exc


@router.post("/dexes/pools/create")
async def create_dex_pool(
    body: CreateDexPoolRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminDexRegistryUseCase = Depends(get_use_case),
):
    try:
        return use_case.create_pool(
            chain=body.chain,
            dex=body.dex,
            pool=body.pool,
            nfpm=body.nfpm,
            gauge=body.gauge,
            token0=body.token0,
            token1=body.token1,
            fee_bps=body.fee_bps,
            pair=body.pair,
            symbol=body.symbol,
            adapter=body.adapter,
            reward_token=body.reward_token,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create dex pool: {exc}") from exc


@router.get("/dexes/pools")
async def list_dex_pools(
    chain: str = Query(...),
    dex: str = Query(...),
    limit: int = Query(500, ge=1, le=5000),
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminDexRegistryUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_pools(chain=chain, dex=dex, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list dex pools: {exc}") from exc
