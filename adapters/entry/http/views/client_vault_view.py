from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.dtos.vault_status_dtos import (
    VaultStatusOut,
)
from adapters.entry.http.dtos.vaults_client_vault_dtos import CreateClientVaultRequest, TxRunResponse
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
            config_in=body.config.model_dump(mode="python"),
            gas_strategy=body.gas_strategy,
        )

        tx_any = out.get("tx")

        if isinstance(tx_any, str):
            tx = {"tx_hash": tx_any, "broadcasted": True, "status": None, "receipt": None, "gas": {}, "budget": {}}
        elif isinstance(tx_any, dict):
            tx = tx_any
        else:
            tx = {"tx_hash": "", "broadcasted": False, "status": None, "receipt": None, "gas": {}, "budget": {}}

        return TxRunResponse(
            tx_hash=str(tx.get("tx_hash") or ""),
            broadcasted=bool(tx.get("broadcasted", True)),
            receipt=(tx.get("receipt") if isinstance(tx.get("receipt"), dict) else tx.get("receipt")),
            status=(tx.get("status") if isinstance(tx.get("status"), int) else None),
            gas=(tx.get("gas") if isinstance(tx.get("gas"), dict) else {}),
            budget=(tx.get("budget") if isinstance(tx.get("budget"), dict) else {}),
            result=(tx.get("result") if isinstance(tx.get("result"), dict) else None),
            ts=(str(tx.get("ts")) if tx.get("ts") is not None else None),
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
