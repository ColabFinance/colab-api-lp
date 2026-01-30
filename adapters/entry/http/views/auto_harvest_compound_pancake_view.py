from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.dtos.auto_harvest_compound_pancake_dtos import (
    HarvestJobPancakeRequest,
    CompoundJobPancakeRequest,
)
from adapters.entry.http.dtos.vaults_client_vault_dtos import TxRunResponse
from core.services.exceptions import TransactionRevertedError, TransactionBudgetExceededError
from core.use_cases.auto_harvest_compound_pancake_usecase import AutoHarvestCompoundPancakeUseCase

router = APIRouter(prefix="/vaults/pancake", tags=["vaults-harvest-compound-pancake"])


def get_use_case() -> AutoHarvestCompoundPancakeUseCase:
    return AutoHarvestCompoundPancakeUseCase.from_settings()


@router.post(
    "/{alias}/harvest-job",
    response_model=TxRunResponse,
    summary="Execute ClientVault.autoHarvestAndCompoundPancake(params) in HARVEST mode for a Pancake vault alias",
)
async def harvest_job(
    alias: str,
    body: HarvestJobPancakeRequest,
    use_case: AutoHarvestCompoundPancakeUseCase = Depends(get_use_case),
):
    try:
        out = use_case.harvest_job(
            alias=alias,
            harvest_pool_fees=body.harvest_pool_fees,
            harvest_rewards=body.harvest_rewards,
            swap_rewards=body.swap_rewards,
            reward_amount_in=body.reward_amount_in,
            reward_amount_out_min=body.reward_amount_out_min,
            reward_sqrt_price_limit_x96=body.reward_sqrt_price_limit_x96,
            gas_strategy=body.gas_strategy,
        )

        return TxRunResponse.from_tx_any(
            tx_any=out.get("tx"),
            vault_address=out.get("vault_address"),
            alias=out.get("alias"),
            mongo_id=None,
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransactionBudgetExceededError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "gas_budget_exceeded",
                "detail": str(exc),
            },
        ) from exc
    except TransactionRevertedError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "reverted_on_chain",
                "tx": exc.tx_hash,
                "receipt": exc.receipt,
                "hint": "Possibly require() failed or out-of-gas.",
                "budget": getattr(exc, "budget_block", None),
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to harvest_job: {exc}") from exc


@router.post(
    "/{alias}/compound-job",
    response_model=TxRunResponse,
    summary="Execute ClientVault.autoHarvestAndCompoundPancake(params) in COMPOUND mode for a Pancake vault alias",
)
async def compound_job(
    alias: str,
    body: CompoundJobPancakeRequest,
    use_case: AutoHarvestCompoundPancakeUseCase = Depends(get_use_case),
):
    try:
        out = use_case.compound_job(
            alias=alias,
            compound0_desired=body.compound0_desired,
            compound1_desired=body.compound1_desired,
            compound0_min=body.compound0_min,
            compound1_min=body.compound1_min,
            gas_strategy=body.gas_strategy,
        )

        return TxRunResponse.from_tx_any(
            tx_any=out.get("tx"),
            vault_address=out.get("vault_address"),
            alias=out.get("alias"),
            mongo_id=None,
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransactionBudgetExceededError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "gas_budget_exceeded",
                "detail": str(exc),
            },
        ) from exc
    except TransactionRevertedError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "reverted_on_chain",
                "tx": exc.tx_hash,
                "receipt": exc.receipt,
                "hint": "Possibly require() failed or out-of-gas.",
                "budget": getattr(exc, "budget_block", None),
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to compound_job: {exc}") from exc
