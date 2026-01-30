from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from adapters.entry.http.dtos.auto_rebalance_pancake_dtos import AutoRebalancePancakeRequest
from adapters.entry.http.dtos.vaults_client_vault_dtos import TxRunResponse
from core.services.exceptions import TransactionRevertedError
from core.use_cases.auto_rebalance_pancake_usecase import AutoRebalancePancakeUseCase

router = APIRouter(prefix="/vaults/pancake", tags=["vaults-auto-rebalance-pancake"])


def get_use_case() -> AutoRebalancePancakeUseCase:
    return AutoRebalancePancakeUseCase.from_settings()


@router.post(
    "/{alias}/auto-rebalance-pancake",
    response_model=TxRunResponse,
    summary="Execute ClientVault.autoRebalancePancake(params) for a Pancake vault alias",
)
async def auto_rebalance_pancake(
    alias: str,
    body: AutoRebalancePancakeRequest,
    use_case: AutoRebalancePancakeUseCase = Depends(get_use_case),
):
    try:
        out = await run_in_threadpool(
            use_case.auto_rebalance_pancake,
            alias=alias,
            lower_tick=body.lower_tick,
            upper_tick=body.upper_tick,
            lower_price=body.lower_price,
            upper_price=body.upper_price,
            fee=body.fee,
            token_in=body.token_in,
            token_out=body.token_out,
            swap_amount_in=body.swap_amount_in,
            swap_amount_out_min=body.swap_amount_out_min,
            sqrt_price_limit_x96=body.sqrt_price_limit_x96,
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
        raise HTTPException(status_code=500, detail=f"Failed to autoRebalancePancake: {exc}") from exc
