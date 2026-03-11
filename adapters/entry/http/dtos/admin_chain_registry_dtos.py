from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from core.domain.enums.chain_registry_enums import ChainRegistryStatus


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def _validate_http_url(value: str, field_name: str) -> str:
    parsed = urlparse((value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be a valid http(s) URL.")
    return value.strip().rstrip("/")


def _dedupe_stables(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for item in values or []:
        symbol = (item or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(symbol)

    return result


class ChainRegistryBaseRequest(BaseModel):
    name: str = Field(..., description="Human-friendly chain name.")
    chain_id: int = Field(..., ge=1, description="EVM chain id.")
    native_symbol: str = Field(..., description="Native gas token symbol.")
    rpc_url: str = Field(..., description="Primary RPC endpoint.")
    explorer_url: str = Field(..., description="Explorer base URL.")
    explorer_label: Optional[str] = Field(default=None, description="Explorer label shown in UI.")
    stables: list[str] = Field(default_factory=list, description="Supported stablecoin symbols.")
    status: ChainRegistryStatus = Field(default=ChainRegistryStatus.ENABLED)
    logo_url: Optional[str] = Field(default=None, description="Optional logo URL.")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("name is required.")
        return value

    @field_validator("native_symbol")
    @classmethod
    def _validate_native_symbol(cls, value: str) -> str:
        value = (value or "").strip().upper()
        if not value:
            raise ValueError("native_symbol is required.")
        return value

    @field_validator("rpc_url")
    @classmethod
    def _validate_rpc_url(cls, value: str) -> str:
        return _validate_http_url(value, "rpc_url")

    @field_validator("explorer_url")
    @classmethod
    def _validate_explorer_url(cls, value: str) -> str:
        return _validate_http_url(value, "explorer_url")

    @field_validator("explorer_label")
    @classmethod
    def _validate_explorer_label(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        vv = value.strip()
        return vv or None

    @field_validator("stables")
    @classmethod
    def _validate_stables(cls, values: list[str]) -> list[str]:
        return _dedupe_stables(values)

    @field_validator("logo_url")
    @classmethod
    def _validate_logo_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        vv = value.strip()
        if not vv:
            return None
        return _validate_http_url(vv, "logo_url")


class CreateChainRequest(ChainRegistryBaseRequest):
    pass


class UpdateChainRequest(ChainRegistryBaseRequest):
    key: str = Field(..., description="Stable registry key.")

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        value = _slugify(value)
        if not value:
            raise ValueError("key is required.")
        return value