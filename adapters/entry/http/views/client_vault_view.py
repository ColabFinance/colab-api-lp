from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.dtos.vault_status_dtos import (
    VaultStatusOut,
)
from adapters.entry.http.dtos.vaults_client_vault_dtos import CreateClientVaultRequest, RegisterClientVaultRequest, TxRunResponse
from core.services.exceptions import TransactionRevertedError
from core.use_cases.vaults_client_vault_usecase import VaultClientVaultUseCase

router = APIRouter(prefix="/vaults", tags=["vaults-client-vault"])


def get_use_case() -> VaultClientVaultUseCase:
    return VaultClientVaultUseCase.from_settings()


@router.get(
    "/{alias_or_address}/status",
    response_model=VaultStatusOut,
    summary="Read-only full status for a given vault (accepts address in {alias_or_address})",
)
async def get_status(alias_or_address: str, use_case: VaultClientVaultUseCase = Depends(get_use_case)):
    try:
        res = use_case.get_status(alias_or_address=alias_or_address)
        return VaultStatusOut(**res)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to get vault status: {exc}") from exc


@router.post(
    "/create-client-vault",
    response_model=TxRunResponse,
    summary="Create ClientVault on-chain and register in Mongo vault_registry",
)
async def create_client_vault(
    body: CreateClientVaultRequest,
    use_case: VaultClientVaultUseCase = Depends(get_use_case),
):
    try:
        out = use_case.create_client_vault_and_register(
            strategy_id=body.strategy_id,
            owner=body.owner,
            chain=body.chain,
            dex=body.dex,
            par_token=body.par_token,
            name=body.name,
            description=body.description,
            config_in=body.config,
            gas_strategy=body.gas_strategy,
        )

        return TxRunResponse.from_tx_any(
            tx_any=out.get("tx"),
            vault_address=out.get("vault_address"),
            alias=out.get("alias"),
            mongo_id=out.get("mongo_id"),
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
        raise HTTPException(status_code=500, detail=f"Failed to createClientVault: {exc}") from exc


@router.post(
    "/register-client-vault",
    summary="Register an existing on-chain ClientVault into Mongo",
)
async def register_client_vault(
    body: RegisterClientVaultRequest,
    use_case: VaultClientVaultUseCase = Depends(get_use_case),
):
    try:
        out = use_case.register_client_vault(
            vault_address=body.vault_address,
            strategy_id=body.strategy_id,
            owner=body.owner,
            chain=body.chain,
            dex=body.dex,
            par_token=body.par_token,
            name=body.name,
            description=body.description,
            config_in=body.config,
        )
        return {
            "alias": out["alias"],
            "mongo_id": out["mongo_id"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

