from time import perf_counter
from fastapi import APIRouter, Depends, HTTPException, Query

from adapters.entry.http.dtos.vault_status_dtos import VaultStatusOut
from adapters.entry.http.dtos.vaults_client_vault_dtos import (
    CreateClientVaultRequest,
    RegisterClientVaultRequest,
    TxRunResponse,
    VaultRegistryOut,
    DailyHarvestConfigUpdateRequest,
    CompoundConfigUpdateRequest,
    RewardSwapConfigUpdateRequest,
)
from adapters.external.signals.signals_http_client import SignalsHttpClient
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
async def get_status(
    alias_or_address: str,
    debug_timing: bool = Query(False, description="Print per-step timings on server logs"),
    use_case: VaultClientVaultUseCase = Depends(get_use_case),
):
    t0 = perf_counter()
    try:
        res = use_case.get_status(alias_or_address=alias_or_address, debug_timing=debug_timing)
        total_ms = (perf_counter() - t0) * 1000.0

        if debug_timing:
            print(f"[vault_status] total_ms={total_ms:.2f} vault={alias_or_address}")
            tm = res.get("_timings_ms")
            if isinstance(tm, dict):
                for k, v in tm.items():
                    try:
                        print(f"  - {k}: {float(v):.2f}ms")
                    except Exception:
                        print(f"  - {k}: {v}")

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

        try:
            alias = str(out.get("alias") or "").strip()
            if alias:
                sig = SignalsHttpClient.from_settings()
                await sig.link_vault_to_strategy(
                    chain=body.chain,
                    owner=body.owner,
                    strategy_id=body.strategy_id,
                    dex=body.dex,
                    alias=alias,
                )
        except Exception as e:
            pass

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
        return {"alias": out["alias"], "mongo_id": out["mongo_id"]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/by-owner",
    response_model=dict,
    summary="List vaults from Mongo registry for an owner (db-only, no onchain scan)",
)
async def list_vaults_by_owner(
    owner: str = Query(..., description="Owner wallet address"),
    chain: str | None = Query(None, description="Optional: base|bnb"),
    dex: str | None = Query(None, description="Optional: pancake|aerodrome|uniswap"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    use_case: VaultClientVaultUseCase = Depends(get_use_case),
):
    try:
        items = use_case.list_registry_by_owner(
            owner=owner,
            chain=chain,
            dex=dex,
            limit=limit,
            offset=offset,
        )
        data = [VaultRegistryOut.model_validate(v.model_dump()) for v in (items or [])]
        return {"ok": True, "message": "ok", "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list vaults: {exc}") from exc


@router.post(
    "/{alias_or_address}/config/daily-harvest",
    response_model=dict,
    summary="Persist daily harvest config in Mongo (no onchain tx here)",
)
async def update_daily_harvest_config(
    alias_or_address: str,
    body: DailyHarvestConfigUpdateRequest,
    use_case: VaultClientVaultUseCase = Depends(get_use_case),
):
    try:
        updated = use_case.update_daily_harvest_config_in_registry(
            alias_or_address=alias_or_address,
            enabled=body.enabled,
            cooldown_sec=body.cooldown_sec,
        )
        return {"ok": True, "message": "ok", "data": VaultRegistryOut.model_validate(updated.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update daily-harvest config: {exc}") from exc


@router.post(
    "/{alias_or_address}/config/compound",
    response_model=dict,
    summary="Persist compound config in Mongo (no onchain tx here)",
)
async def update_compound_config(
    alias_or_address: str,
    body: CompoundConfigUpdateRequest,
    use_case: VaultClientVaultUseCase = Depends(get_use_case),
):
    try:
        updated = use_case.update_compound_config_in_registry(
            alias_or_address=alias_or_address,
            enabled=body.enabled,
            cooldown_sec=body.cooldown_sec,
        )
        return {"ok": True, "message": "ok", "data": VaultRegistryOut.model_validate(updated.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update compound config: {exc}") from exc


@router.post(
    "/{alias_or_address}/config/reward-swap",
    response_model=dict,
    summary="Persist reward swap config in Mongo (no onchain tx here)",
)
async def update_reward_swap_config(
    alias_or_address: str,
    body: RewardSwapConfigUpdateRequest,
    use_case: VaultClientVaultUseCase = Depends(get_use_case),
):
    try:
        updated = use_case.update_reward_swap_config_in_registry(
            alias_or_address=alias_or_address,
            enabled=body.enabled,
            token_in=body.token_in,
            token_out=body.token_out,
            fee=body.fee,
            sqrt_price_limit_x96=body.sqrt_price_limit_x96,
        )
        return {"ok": True, "message": "ok", "data": VaultRegistryOut.model_validate(updated.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update reward-swap config: {exc}") from exc
