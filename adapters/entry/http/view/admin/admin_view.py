from __future__ import annotations

from fastapi import APIRouter, Depends

from adapters.entry.http.view.admin.admin_auth import AdminPrincipal, require_admin
from adapters.external.database.factory_repository import StrategyFactoryRepo, VaultFactoryRepo

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/strategy-factory")
async def create_strategy_factory(_: AdminPrincipal = Depends(require_admin)):
    repo = StrategyFactoryRepo()
    # payload can include chain, contract addresses, versioning, etc.
    return repo.create_if_allowed(payload={"type": "strategy_factory"})


@router.post("/vault-factory")
async def create_vault_factory(_: AdminPrincipal = Depends(require_admin)):
    repo = VaultFactoryRepo()
    return repo.create_if_allowed(payload={"type": "vault_factory"})


@router.get("/owners")
async def list_owners(_: AdminPrincipal = Depends(require_admin)):
    """
    Current implementation: best-effort owners list derived from Mongo vault registry/state.
    If you don't have a dedicated collection yet, return an empty list.
    """
    # TODO: implement using vault_registry_repository / vault_repo.
    return []


@router.get("/users")
async def list_users(_: AdminPrincipal = Depends(require_admin)):
    """
    Temporary alias:
    - Until api-lp persists Privy users, return the same as owners.
    """
    return []
