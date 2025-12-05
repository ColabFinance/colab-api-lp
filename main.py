# main.py
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from adapters.external.database.vault_events_repository import VaultEventsRepository
from adapters.external.database.vault_registry_repository import VaultRegistryRepository
from adapters.external.database.vault_state_repository import VaultStateRepository
from adapters.entry.http.view.vaults_registry import router as vaults_registry_router
from adapters.entry.http.view.vaults_position import router as vaults_position_router
from adapters.entry.http.view.vaults_swap import router as vaults_swap_router
from adapters.entry.http.view.vaults_batch import router as vaults_batch_router


def init_mongo_indexes() -> None:
    """
    Initialize MongoDB indexes for all vault-related collections.

    This makes sure the application has the expected indexes for efficient
    queries and unique constraints before serving any request.
    """
    # Vault registry: __init__ already ensures its own indexes
    VaultRegistryRepository()

    # Vault state indexes
    state_repo = VaultStateRepository()
    state_repo.ensure_indexes()

    # Vault events indexes
    events_repo = VaultEventsRepository()
    events_repo.ensure_indexes()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context.

    Runs once on startup (before the first request) and once on shutdown.
    Here we make sure MongoDB indexes exist before handling traffic.
    """
    init_mongo_indexes()
    yield
    # No special shutdown logic needed for now.


def create_app() -> FastAPI:
    """
    Application factory for the DEX Vault API.

    Wires routes and configures the application lifespan so that infrastructure
    (MongoDB indexes) is ready before processing requests.
    """
    app = FastAPI(
        title="DEX Vault API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(vaults_registry_router, prefix="/api")
    app.include_router(vaults_position_router, prefix="/api")
    app.include_router(vaults_swap_router, prefix="/api")
    app.include_router(vaults_batch_router, prefix="/api")

    return app


app = create_app()
