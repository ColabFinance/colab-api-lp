from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.dtos.vaults_client_vault_dtos import (
    ExitWithdrawRequest,
    SetAutomationConfigRequest,
    SetAutomationEnabledRequest,
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
    "/{alias}/set-automation-enabled",
    response_model=TxRunResponse,
    summary="setAutomationEnabled (signed by backend PK)",
)
async def set_automation_enabled(alias: str, body: SetAutomationEnabledRequest, use_case: VaultClientVaultUseCase = Depends(get_use_case)):
    try:
        res = use_case.set_automation_enabled(
            alias_or_address=alias,
            enabled=body.enabled,
            gas_strategy=body.gas_strategy,
        )
        return TxRunResponse(**res)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransactionRevertedError as exc:
        raise HTTPException(status_code=500, detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to setAutomationEnabled: {exc}") from exc


@router.post(
    "/{alias}/set-automation-config",
    response_model=TxRunResponse,
    summary="setAutomationConfig (signed by backend PK)",
)
async def set_automation_config(alias: str, body: SetAutomationConfigRequest, use_case: VaultClientVaultUseCase = Depends(get_use_case)):
    try:
        res = use_case.set_automation_config(
            alias_or_address=alias,
            cooldown_sec=body.cooldown_sec,
            max_slippage_bps=body.max_slippage_bps,
            allow_swap=body.allow_swap,
            gas_strategy=body.gas_strategy,
        )
        return TxRunResponse(**res)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransactionRevertedError as exc:
        raise HTTPException(status_code=500, detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to setAutomationConfig: {exc}") from exc


@router.post(
    "/{alias}/collect",
    response_model=TxRunResponse,
    summary="collectToVault (signed by backend PK)",
)
async def collect(alias: str, use_case: VaultClientVaultUseCase = Depends(get_use_case)):
    try:
        res = use_case.collect(alias_or_address=alias, gas_strategy="buffered")
        return TxRunResponse(**res)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransactionRevertedError as exc:
        raise HTTPException(status_code=500, detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to collectToVault: {exc}") from exc


@router.post(
    "/{alias}/exit",
    response_model=TxRunResponse,
    summary="exitPositionToVault (signed by backend PK)",
)
async def exit_position(alias: str, use_case: VaultClientVaultUseCase = Depends(get_use_case)):
    try:
        res = use_case.exit_to_vault(alias_or_address=alias, gas_strategy="buffered")
        return TxRunResponse(**res)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransactionRevertedError as exc:
        raise HTTPException(status_code=500, detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to exitPositionToVault: {exc}") from exc


@router.post(
    "/{alias}/exit-withdraw",
    response_model=TxRunResponse,
    summary="exitPositionAndWithdrawAll(to) (signed by backend PK)",
)
async def exit_withdraw(alias: str, body: ExitWithdrawRequest, use_case: VaultClientVaultUseCase = Depends(get_use_case)):
    try:
        res = use_case.exit_withdraw_all(
            alias_or_address=alias,
            to=body.to,
            gas_strategy=body.gas_strategy,
        )
        return TxRunResponse(**res)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransactionRevertedError as exc:
        raise HTTPException(status_code=500, detail={"error": "reverted_on_chain", "tx": exc.tx_hash, "receipt": exc.receipt}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to exitWithdrawAll: {exc}") from exc
