from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.dtos.admin_vault_fee_buffer_dtos import CreateVaultFeeBufferRequest
from adapters.entry.http.views.admin.admin_auth import AdminPrincipal, require_admin
from core.services.exceptions import TransactionRevertedError
from core.use_cases.admin_vault_fee_buffer_usecase import AdminVaultFeeBufferUseCase

router = APIRouter(prefix="/admin", tags=["admin"])


def get_use_case() -> AdminVaultFeeBufferUseCase:
    return AdminVaultFeeBufferUseCase.from_settings()


@router.post("/vault-fee-buffer/create")
async def create_vault_fee_buffer(
    body: CreateVaultFeeBufferRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminVaultFeeBufferUseCase = Depends(get_use_case),
):
    """
    Deploy VaultFeeBuffer on-chain and persist it to MongoDB.
    """
    try:
        initial_owner = (body.initial_owner or admin.wallet_address or "").strip()

        return use_case.create_vault_fee_buffer(
            chain=body.chain,
            initial_owner=initial_owner,
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
        raise HTTPException(status_code=500, detail=f"Failed to create vault fee buffer: {exc}") from exc
