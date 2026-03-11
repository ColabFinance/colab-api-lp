from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from adapters.external.database.chain_registry_repository_mongodb import ChainRegistryRepositoryMongoDB

from core.domain.entities.chain_registry_entity import ChainRegistryEntity
from core.domain.enums.chain_registry_enums import ChainRegistryStatus
from core.domain.repositories.chain_registry_repository_interface import ChainRegistryRepository


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def _require_text(field_name: str, value: str) -> str:
    vv = (value or "").strip()
    if not vv:
        raise ValueError(f"{field_name} is required.")
    return vv


def _norm_symbol(value: str) -> str:
    return _require_text("native_symbol", value).upper()


def _norm_stables(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for item in values or []:
        symbol = (item or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(symbol)

    return result


def _build_explorer_label(explorer_url: str, explorer_label: Optional[str]) -> str:
    label = (explorer_label or "").strip()
    if label:
        return label

    parsed = urlparse((explorer_url or "").strip())
    return parsed.netloc or explorer_url


@dataclass
class AdminChainRegistryUseCase:
    repo: ChainRegistryRepository

    @classmethod
    def from_settings(cls) -> "AdminChainRegistryUseCase":
        repo = ChainRegistryRepositoryMongoDB()
        try:
            repo.ensure_indexes()
        except Exception:
            pass
        return cls(repo=repo)

    def create_chain(
        self,
        *,
        name: str,
        chain_id: int,
        native_symbol: str,
        rpc_url: str,
        explorer_url: str,
        explorer_label: Optional[str] = None,
        stables: Optional[list[str]] = None,
        status: ChainRegistryStatus = ChainRegistryStatus.ENABLED,
        logo_url: Optional[str] = None,
    ) -> dict:
        name_in = _require_text("name", name)
        key = _slugify(name_in)
        if not key:
            raise ValueError("Could not generate a valid key from name.")

        chain_id_in = int(chain_id)
        if chain_id_in <= 0:
            raise ValueError("chain_id must be greater than zero.")

        if self.repo.get_by_key(key=key):
            raise ValueError("Chain already exists for this key.")

        if self.repo.get_by_chain_id(chain_id=chain_id_in):
            raise ValueError("Chain already exists for this chain_id.")

        entity = ChainRegistryEntity(
            key=key,
            name=name_in,
            chain_id=chain_id_in,
            status=status,
            rpc_url=_require_text("rpc_url", rpc_url),
            explorer_url=_require_text("explorer_url", explorer_url),
            explorer_label=_build_explorer_label(explorer_url, explorer_label),
            native_symbol=_norm_symbol(native_symbol),
            stables=_norm_stables(stables or []),
            logo_url=(logo_url or "").strip(),
        )
        self.repo.insert(entity)

        return {
            "ok": True,
            "message": "Chain created.",
            "data": self._serialize(entity),
        }

    def update_chain(
        self,
        *,
        key: str,
        name: str,
        chain_id: int,
        native_symbol: str,
        rpc_url: str,
        explorer_url: str,
        explorer_label: Optional[str] = None,
        stables: Optional[list[str]] = None,
        status: ChainRegistryStatus = ChainRegistryStatus.ENABLED,
        logo_url: Optional[str] = None,
    ) -> dict:
        key_in = _slugify(key)
        if not key_in:
            raise ValueError("key is required.")

        current = self.repo.get_by_key(key=key_in)
        if not current:
            raise ValueError("Chain registry not found.")

        chain_id_in = int(chain_id)
        if chain_id_in <= 0:
            raise ValueError("chain_id must be greater than zero.")

        duplicate_chain_id = self.repo.get_by_chain_id(chain_id=chain_id_in)
        if duplicate_chain_id and duplicate_chain_id.key != current.key:
            raise ValueError("Another chain already uses this chain_id.")

        entity = ChainRegistryEntity(
            id=current.id,
            created_at=current.created_at,
            created_at_iso=current.created_at_iso,
            key=current.key,
            name=_require_text("name", name),
            chain_id=chain_id_in,
            status=status,
            rpc_url=_require_text("rpc_url", rpc_url),
            explorer_url=_require_text("explorer_url", explorer_url),
            explorer_label=_build_explorer_label(explorer_url, explorer_label),
            native_symbol=_norm_symbol(native_symbol),
            stables=_norm_stables(stables or []),
            logo_url=(logo_url or "").strip(),
        )
        self.repo.update(entity)

        return {
            "ok": True,
            "message": "Chain updated.",
            "data": self._serialize(entity),
        }

    def list_chains(self, *, limit: int = 200) -> dict:
        rows = self.repo.list_all(limit=int(limit))
        data = [self._serialize(row) for row in rows]
        return {
            "ok": True,
            "message": "OK",
            "data": data,
        }

    @staticmethod
    def _serialize(entity: ChainRegistryEntity) -> dict:
        return {
            "id": entity.id,
            "key": entity.key,
            "name": entity.name,
            "chain_id": entity.chain_id,
            "status": entity.status,
            "rpc_url": entity.rpc_url,
            "explorer_url": entity.explorer_url,
            "explorer_label": entity.explorer_label,
            "native_symbol": entity.native_symbol,
            "stables": entity.stables,
            "logo_url": entity.logo_url,
            "created_at": entity.created_at,
            "created_at_iso": entity.created_at_iso,
            "updated_at": entity.updated_at,
            "updated_at_iso": entity.updated_at_iso,
        }