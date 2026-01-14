from __future__ import annotations

from fastapi import APIRouter

from adapters.entry.http.views.admin.admin_strategy_view import router as strategy_router
from adapters.entry.http.views.admin.admin_vault_factory_view import router as vault_factory_router
from adapters.entry.http.views.admin.admin_adapters_view import router as adapters_router

router = APIRouter()
router.include_router(strategy_router)
router.include_router(vault_factory_router)
router.include_router(adapters_router)
