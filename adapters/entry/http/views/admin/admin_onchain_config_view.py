from fastapi import APIRouter, Depends, HTTPException, Query

from adapters.entry.http.dtos.admin_onchain_config_dtos import (
    SaveProtocolFeeCollectorStateRequest,
    SaveProtocolFeeReporterStateRequest,
    SaveStrategyAdapterStateRequest,
    SaveStrategyRouterStateRequest,
    SaveVaultFactoryStateRequest,
    SaveVaultFeeBufferDepositorStateRequest,
)
from adapters.entry.http.views.admin.admin_auth import AdminPrincipal, require_admin
from core.use_cases.admin_onchain_config_usecase import AdminOnchainConfigUseCase

router = APIRouter(prefix="/admin/onchain-config", tags=["admin"])


def get_use_case() -> AdminOnchainConfigUseCase:
    return AdminOnchainConfigUseCase.from_settings()


@router.get("/strategy-registry")
async def list_strategy_registry_state(
    chain: str = Query(..., description='Chain key (e.g. "base", "bnb")'),
    limit: int = Query(500, ge=1, le=2000),
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminOnchainConfigUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_strategy_registry_state(chain=chain, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch StrategyRegistry state: {exc}") from exc


@router.post("/strategy-registry/router")
async def save_strategy_router_state(
    body: SaveStrategyRouterStateRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminOnchainConfigUseCase = Depends(get_use_case),
):
    try:
        return use_case.save_strategy_router_state(
            chain=body.chain,
            contract_address=body.contract_address,
            address=body.address,
            name=body.name,
            allowed=body.allowed,
            tx_hash=body.tx_hash,
            updated_by=admin.wallet_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save router state: {exc}") from exc


@router.post("/strategy-registry/adapter")
async def save_strategy_adapter_state(
    body: SaveStrategyAdapterStateRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminOnchainConfigUseCase = Depends(get_use_case),
):
    try:
        return use_case.save_strategy_adapter_state(
            chain=body.chain,
            contract_address=body.contract_address,
            address=body.address,
            label=body.label,
            adapter_type=body.adapter_type,
            allowed=body.allowed,
            tx_hash=body.tx_hash,
            updated_by=admin.wallet_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save adapter state: {exc}") from exc


@router.get("/vault-factory")
async def list_vault_factory_state(
    chain: str = Query(..., description='Chain key (e.g. "base", "bnb")'),
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminOnchainConfigUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_vault_factory_state(chain=chain)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch VaultFactory state: {exc}") from exc


@router.post("/vault-factory")
async def save_vault_factory_state(
    body: SaveVaultFactoryStateRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminOnchainConfigUseCase = Depends(get_use_case),
):
    try:
        return use_case.save_vault_factory_state(
            chain=body.chain,
            contract_address=body.contract_address,
            executor=body.executor,
            fee_collector=body.fee_collector,
            default_cooldown_sec=body.default_cooldown_sec,
            default_max_slippage_bps=body.default_max_slippage_bps,
            default_allow_swap=body.default_allow_swap,
            tx_hash=body.tx_hash,
            updated_by=admin.wallet_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save VaultFactory state: {exc}") from exc


@router.get("/protocol-fee-collector")
async def list_protocol_fee_collector_state(
    chain: str = Query(..., description='Chain key (e.g. "base", "bnb")'),
    limit: int = Query(500, ge=1, le=2000),
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminOnchainConfigUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_protocol_fee_collector_state(chain=chain, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch ProtocolFeeCollector state: {exc}") from exc


@router.post("/protocol-fee-collector")
async def save_protocol_fee_collector_state(
    body: SaveProtocolFeeCollectorStateRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminOnchainConfigUseCase = Depends(get_use_case),
):
    try:
        return use_case.save_protocol_fee_collector_state(
            chain=body.chain,
            contract_address=body.contract_address,
            treasury=body.treasury,
            protocol_fee_bps=body.protocol_fee_bps,
            tx_hash=body.tx_hash,
            updated_by=admin.wallet_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save ProtocolFeeCollector state: {exc}") from exc


@router.post("/protocol-fee-collector/reporter")
async def save_protocol_fee_reporter_state(
    body: SaveProtocolFeeReporterStateRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminOnchainConfigUseCase = Depends(get_use_case),
):
    try:
        return use_case.save_protocol_fee_reporter_state(
            chain=body.chain,
            contract_address=body.contract_address,
            reporter=body.reporter,
            allowed=body.allowed,
            tx_hash=body.tx_hash,
            updated_by=admin.wallet_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save reporter state: {exc}") from exc


@router.get("/vault-fee-buffer")
async def list_vault_fee_buffer_state(
    chain: str = Query(..., description='Chain key (e.g. "base", "bnb")'),
    limit: int = Query(500, ge=1, le=2000),
    _: AdminPrincipal = Depends(require_admin),
    use_case: AdminOnchainConfigUseCase = Depends(get_use_case),
):
    try:
        return use_case.list_vault_fee_buffer_state(chain=chain, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch VaultFeeBuffer state: {exc}") from exc


@router.post("/vault-fee-buffer/depositor")
async def save_vault_fee_buffer_depositor_state(
    body: SaveVaultFeeBufferDepositorStateRequest,
    admin: AdminPrincipal = Depends(require_admin),
    use_case: AdminOnchainConfigUseCase = Depends(get_use_case),
):
    try:
        return use_case.save_vault_fee_buffer_depositor_state(
            chain=body.chain,
            contract_address=body.contract_address,
            depositor=body.depositor,
            label=body.label,
            allowed=body.allowed,
            tx_hash=body.tx_hash,
            updated_by=admin.wallet_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save depositor state: {exc}") from exc