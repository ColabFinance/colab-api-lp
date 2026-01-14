from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from core.use_cases.contracts_registry_usecase import ContractsRegistryUseCase


router = APIRouter(prefix="/contracts", tags=["contracts"])


def get_use_case() -> ContractsRegistryUseCase:
    return ContractsRegistryUseCase.from_settings()


@router.get("/registry")
async def get_contracts_registry(
    chain: str = Query(..., description='Chain key (e.g. "base", "bnb")'),
    use_case: ContractsRegistryUseCase = Depends(get_use_case),
):
    """
    Returns the active on-chain contract addresses for a given chain.

    This endpoint is intended for frontend bootstrapping:
      - strategy factory (ACTIVE)
      - vault factory (ACTIVE)
      - adapters (ACTIVE)
    """
    try:
        dto = use_case.get_registry(chain=chain)
        return {"ok": True, "message": "ok", "data": dto.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load contracts registry: {exc}") from exc
