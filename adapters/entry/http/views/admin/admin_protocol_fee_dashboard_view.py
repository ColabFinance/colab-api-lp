from fastapi import APIRouter, Depends, HTTPException, Query

from adapters.entry.http.dtos.admin_protocol_fee_dashboard_dtos import (
    RecordProtocolFeeWithdrawalRequest,
    TrackProtocolFeeTokenRequest,
)
from adapters.entry.http.views.admin.admin_auth import AdminPrincipal, require_admin
from core.use_cases.admin_protocol_fee_dashboard_usecase import (
    AdminProtocolFeeDashboardUseCase,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def get_use_case() -> AdminProtocolFeeDashboardUseCase:
    return AdminProtocolFeeDashboardUseCase.from_settings()


@router.get("/protocol-fee-collector/dashboard")
async def get_protocol_fee_dashboard(
    chain: str = Query(..., description='Chain key (e.g. "base", "bnb")'),
    tracked_limit: int = Query(300, ge=1, le=1000),
    withdrawal_limit: int = Query(100, ge=1, le=500),
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminProtocolFeeDashboardUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_dashboard(
            chain=chain,
            tracked_limit=tracked_limit,
            withdrawal_limit=withdrawal_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch protocol fee dashboard: {exc}") from exc


@router.post("/protocol-fee-collector/tracked-token")
async def track_protocol_fee_token(
    body: TrackProtocolFeeTokenRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminProtocolFeeDashboardUseCase = Depends(get_use_case),
):
    try:
        return use_case.track_token(
            chain=body.chain,
            contract_address=body.contract_address,
            token_address=body.token_address,
            label=body.label,
            created_by=admin.wallet_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to track token: {exc}") from exc


@router.post("/protocol-fee-collector/withdrawal")
async def record_protocol_fee_withdrawal(
    body: RecordProtocolFeeWithdrawalRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminProtocolFeeDashboardUseCase = Depends(get_use_case),
):
    try:
        return use_case.record_withdrawal(
            chain=body.chain,
            contract_address=body.contract_address,
            tx_hash=body.tx_hash,
            token_address=body.token_address,
            token_symbol=body.token_symbol,
            amount_raw=body.amount_raw,
            amount_label=body.amount_label,
            destination=body.destination,
            status=body.status,
            created_by=admin.wallet_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to record withdrawal: {exc}") from exc