from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.views.admin.admin_auth import require_admin, AdminPrincipal
from adapters.entry.http.dtos.admin_protocol_fee_collector_dtos import CreateProtocolFeeCollectorRequest
from core.use_cases.admin_protocol_fee_collector_usecase import AdminProtocolFeeCollectorUseCase
from core.services.exceptions import TransactionRevertedError

router = APIRouter(prefix="/admin", tags=["admin"])


def get_use_case() -> AdminProtocolFeeCollectorUseCase:
    return AdminProtocolFeeCollectorUseCase.from_settings()


@router.post("/protocol-fee-collector/create")
async def create_protocol_fee_collector(
    body: CreateProtocolFeeCollectorRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminProtocolFeeCollectorUseCase = Depends(get_use_case),
):
    """
    Deploy ProtocolFeeCollector on-chain and persist it to MongoDB.
    """
    try:
        initial_owner = (body.initial_owner or admin.wallet_address or "").strip()
        treasury = (body.treasury or "").strip()

        return use_case.create_protocol_fee_collector(
            chain=body.chain,
            initial_owner=initial_owner,
            treasury=treasury,
            protocol_fee_bps=int(body.protocol_fee_bps),
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
        raise HTTPException(status_code=500, detail=f"Failed to create protocol fee collector: {exc}") from exc
