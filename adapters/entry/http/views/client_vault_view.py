from fastapi import APIRouter, Depends, HTTPException, Path

from adapters.entry.http.dtos.vaults_client_vault_dtos import (
    AutoRebalancePancakeIn,
    CreateClientVaultRequest,
    TxRunResponse,
    VaultStatusOut,
)
from core.services.exceptions import TransactionRevertedError
from core.use_cases.vaults_client_vault_usecase import VaultClientVaultUseCase

router = APIRouter(prefix="/vaults", tags=["vaults-client-vault"])


def get_use_case() -> VaultClientVaultUseCase:
    return VaultClientVaultUseCase.from_settings()


@router.get(
    "/{alias}/status",
    response_model=VaultStatusOut,
    summary="Read-only full status for a given vault (accepts address in {alias})",
)
async def get_status(alias: str, use_case: VaultClientVaultUseCase = Depends(get_use_case)):
    try:
        res = use_case.get_status(alias_or_address=alias)
        return VaultStatusOut(**res)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to get vault status: {exc}") from exc


@router.post(
    "/factory/create-client-vault",
    response_model=TxRunResponse,
    summary="Executa createClientVault (assinando no backend PK) - estilo deposit_uc",
)
async def create_client_vault(
    body: CreateClientVaultRequest,
    use_case: VaultClientVaultUseCase = Depends(get_use_case),
):
    try:
        res = use_case.create_client_vault(
            strategy_id=body.strategy_id,
            owner_override=body.owner_override,
            gas_strategy=body.gas_strategy,
        )
        return TxRunResponse(**res)
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
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to createClientVault: {exc}") from exc


@router.post("/{alias_or_address}/auto-rebalance-pancake")
def auto_rebalance_pancake(payload: AutoRebalancePancakeIn, alias_or_address: str = Path(...)):
    uc = VaultClientVaultUseCase.from_settings()
    try:
        res = uc.auto_rebalance_pancake(
            alias_or_address=alias_or_address,
            params=payload.model_dump(exclude={"gas_strategy"}),
            gas_strategy=payload.gas_strategy,
        )
        return {"data": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e