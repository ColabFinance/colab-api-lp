from fastapi import APIRouter

from core.domain.models import (
    DexName,
    VaultList,
    AddVaultRequest,
    SetPoolRequest,
    DeployVaultRequest,
    BaselineRequest,
    StatusResponse,
)
from core.use_cases.vaults_registry_usecase import (
    list_vaults_uc,
    add_vault_uc,
    set_pool_uc,
    deploy_vault_uc,
    baseline_uc,
    status_uc,
)

router = APIRouter(tags=["vaults-registry"], prefix="/vaults")


@router.get("/{dex}", response_model=VaultList)
def list_vaults(dex: DexName):
    return list_vaults_uc(dex)


@router.post("/{dex}/add")
def add_vault(dex: str, req: AddVaultRequest):
    return add_vault_uc(dex, req)


@router.post("/{dex}/{alias}/set-pool")
def set_pool(dex: str, alias: str, req: SetPoolRequest):
    return set_pool_uc(dex, alias, req)


@router.get("/{dex}/{alias}/status", response_model=StatusResponse)
def status(dex: str, alias: str):
    return status_uc(dex, alias)


@router.post("/{dex}/{alias}/baseline")
def baseline(dex: str, alias: str, req: BaselineRequest):
    return baseline_uc(dex, alias, req)


@router.post("/{dex}/deploy")
def deploy_vault(dex: str, req: DeployVaultRequest):
    return deploy_vault_uc(dex, req)
