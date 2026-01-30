from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from core.use_cases.dex_registry_usecase import DexRegistryUseCase


router = APIRouter(prefix="/dexes", tags=["dex"])


def get_use_case() -> DexRegistryUseCase:
    return DexRegistryUseCase.from_settings()

@router.get("")
async def list_dex_registries(
    chain: str = Query(..., description='Chain key (e.g. "base", "bnb")'),
    limit: int = Query(200, ge=1, le=1000),
    use_case: DexRegistryUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_dexes(chain=chain, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list dex registries: {exc}") from exc


@router.get("/pools")
async def list_dex_pools(
    chain: str = Query(...),
    dex: str = Query(...),
    limit: int = Query(500, ge=1, le=5000),
    use_case: DexRegistryUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_pools(chain=chain, dex=dex, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list dex pools: {exc}") from exc


@router.get("/pools/by-pool")
async def get_pool_by_pool(
    pool: str = Query(...),
    use_case: DexRegistryUseCase = Depends(get_use_case),
):
    try:
        return use_case.get_pool_by_pool(pool=pool)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to get dex pool by pool: {exc}") from exc
