from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from adapters.entry.http.dtos.vault_performance_dtos import VaultPerformanceResponse, VaultPerformanceData
from core.use_cases.vault_performance_usecase import VaultPerformanceUseCase


router = APIRouter(prefix="/vaults", tags=["vault-performance"])


def get_use_case() -> VaultPerformanceUseCase:
    return VaultPerformanceUseCase.from_settings()


@router.get(
    "/{alias_or_address}/performance",
    response_model=VaultPerformanceResponse,
    summary="Get full vault performance (episodes + events + cashflows + profit/APR/APY), front-ready",
)
async def get_vault_performance(
    alias_or_address: str,
    episodes_limit: int = Query(300, ge=1, le=1000),
    use_case: VaultPerformanceUseCase = Depends(get_use_case),
):
    try:
        # (opcional) se você quiser autorizar por owner, dá pra checar aqui usando vault_registry.owner
        data = await use_case.build_performance(
            alias_or_address=alias_or_address,
            episodes_limit=int(episodes_limit),
        )
        return VaultPerformanceResponse(ok=True, message="ok", data=VaultPerformanceData.model_validate(data))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build performance: {exc}") from exc
