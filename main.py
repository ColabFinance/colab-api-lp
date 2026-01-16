# main.py
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from adapters.external.database.vault_events_repository_mongodb import VaultEventsRepository
from adapters.external.database.vault_state_repository import VaultStateRepository
from adapters.entry.http.views.client_vault_view import router as vaults_client_vault_router
from adapters.entry.http.views.admin.admin_view import router as admin_router
from adapters.entry.http.views.contracts_address_view import router as contracts_router
from adapters.entry.http.views.auto_rebalance_pancake_view import router as auto_rebalance_pancake_router

def init_mongo_indexes() -> None:
    """
    Initialize MongoDB indexes for all vault-related collections.

    This makes sure the application has the expected indexes for efficient
    queries and unique constraints before serving any request.
    """

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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
        
    app.include_router(admin_router, prefix="/api")
    app.include_router(vaults_client_vault_router, prefix="/api")
    app.include_router(contracts_router, prefix="/api")
    app.include_router(auto_rebalance_pancake_router, prefix="/api")
    
    return app


app = create_app()
