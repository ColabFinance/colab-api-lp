from fastapi import APIRouter, Depends, HTTPException

from adapters.entry.http.dtos.vaults_strategy_registry_dtos import RegisterStrategyTxRequest, SetStrategyActiveTxRequest, StrategyOnchainOut, UpdateStrategyTxRequest
from core.services.exceptions import TransactionRevertedError
from core.use_cases.vaults_factory_usecase import VaultFactoryUseCase
from core.use_cases.vaults_strategy_registry_usecase import VaultStrategyRegistryUseCase

router = APIRouter(
    prefix="/vaults",
    tags=["vaults-strategy-registry"],
)

def get_use_case() -> VaultStrategyRegistryUseCase:
    """
    Dependency para criar o use case já com Web3 + adapters configurados.
    """
    return VaultStrategyRegistryUseCase.from_settings()



@router.get(
    "/strategies/{strategy_id}",
    response_model=StrategyOnchainOut,
    summary="Ler metadados de uma Strategy direto do contrato StrategyRegistry",
)
async def get_strategy_onchain(
    strategy_id: int,
    use_case: VaultStrategyRegistryUseCase = Depends(get_use_case),
):
    try:
        s = use_case.get_strategy(strategy_id)
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy {strategy_id} not found on-chain: {exc}",
        ) from exc

    return StrategyOnchainOut(
        strategy_id=strategy_id,
        adapter=s["adapter"],
        dex_router=s["dex_router"],
        token0=s["token0"],
        token1=s["token1"],
        name=s["name"],
        description=s["description"],
        active=s["active"],
    )


@router.post(
    "/strategies/register",
    summary="Executar StrategyRegistry.registerStrategy (backend assina, onlyOwner)",
)
async def register_strategy(
    body: RegisterStrategyTxRequest,
    use_case: VaultStrategyRegistryUseCase = Depends(get_use_case),
):
    try:
        # note: admin_wallet do DTO fica ignorado aqui; backend assina com PRIVATE_KEY
        res = use_case.register_strategy(
            adapter=body.adapter,
            dex_router=body.dex_router,
            token0=body.token0,
            token1=body.token1,
            name=body.name,
            description=body.description,
        )
        return res
    except TransactionRevertedError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "reverted_on_chain",
                "tx": e.tx_hash,
                "receipt": e.receipt,
                "hint": "Likely onlyOwner, invalid params, or require() failed.",
            },
        ) from e
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"registerStrategy failed: {exc}") from exc


@router.post(
    "/strategies/update",
    summary="Executar StrategyRegistry.updateStrategy (backend assina, onlyOwner)",
)
async def update_strategy(
    body: UpdateStrategyTxRequest,
    use_case: VaultStrategyRegistryUseCase = Depends(get_use_case),
):
    try:
        res = use_case.update_strategy(
            strategy_id=body.strategy_id,
            adapter=body.adapter,
            dex_router=body.dex_router,
            token0=body.token0,
            token1=body.token1,
            name=body.name,
            description=body.description,
        )
        return res
    except TransactionRevertedError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "reverted_on_chain",
                "tx": e.tx_hash,
                "receipt": e.receipt,
                "hint": "Likely onlyOwner or require() failed.",
            },
        ) from e
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"updateStrategy failed: {exc}") from exc


@router.post(
    "/strategies/set-active",
    summary="Executar StrategyRegistry.setStrategyActive (backend assina, onlyOwner)",
)
async def set_strategy_active(
    body: SetStrategyActiveTxRequest,
    use_case: VaultStrategyRegistryUseCase = Depends(get_use_case),
):
    try:
        res = use_case.set_strategy_active(strategy_id=body.strategy_id, active=body.active)
        return res
    except TransactionRevertedError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "reverted_on_chain",
                "tx": e.tx_hash,
                "receipt": e.receipt,
                "hint": "Likely onlyOwner or require() failed.",
            },
        ) from e
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"setStrategyActive failed: {exc}") from exc