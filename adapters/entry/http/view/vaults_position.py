from fastapi import APIRouter, HTTPException

from core.domain.models import (
    OpenRequest,
    RebalanceRequest,
    WithdrawRequest,
    CollectRequest,
    DepositRequest,
    StakeRequest,
    UnstakeRequest,
    ClaimRewardsRequest,
)
from core.use_cases.vaults_position_usecase import (
    open_position_uc,
    rebalance_caps_uc,
    withdraw_uc,
    collect_uc,
    deposit_uc,
    stake_nft_uc,
    unstake_nft_uc,
    claim_rewards_uc,
)

router = APIRouter(tags=["vaults-position"], prefix="/vaults")


@router.post("/{dex}/{alias}/open")
def open_position(dex: str, alias: str, req: OpenRequest):
    return open_position_uc(dex, alias, req)


@router.post("/{dex}/{alias}/rebalance")
def rebalance_caps(dex: str, alias: str, req: RebalanceRequest):
    return rebalance_caps_uc(dex, alias, req)


@router.post("/{dex}/{alias}/withdraw")
def withdraw(dex: str, alias: str, req: WithdrawRequest):
    return withdraw_uc(dex, alias, req)


@router.post("/{dex}/{alias}/collect")
def collect(dex: str, alias: str, req: CollectRequest):
    return collect_uc(dex, alias, req)


@router.post("/{dex}/{alias}/deposit")
def deposit(dex: str, alias: str, req: DepositRequest):
    return deposit_uc(dex, alias, req)


@router.post("/{dex}/{alias}/stake")
def stake_nft(dex: str, alias: str, req: StakeRequest):
    return stake_nft_uc(dex, alias, req)


@router.post("/{dex}/{alias}/unstake")
def unstake_nft(dex: str, alias: str, req: UnstakeRequest):
    return unstake_nft_uc(dex, alias, req)


@router.post("/{dex}/{alias}/claim")
def claim_rewards(dex: str, alias: str, req: ClaimRewardsRequest):
    try:
        return claim_rewards_uc(dex, alias, req)
    except NotImplementedError as e:
        # enquanto você não mover a lógica, retorno amigável
        raise HTTPException(501, str(e))
