from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from config import get_settings


@dataclass
class SignalsHttpClient:
    base_url: str

    @classmethod
    def from_settings(cls) -> "SignalsHttpClient":
        st = get_settings()
        return cls(base_url=(st.API_SIGNALS_URL or "").rstrip("/"))

    async def list_episodes_by_vault(
        self,
        *,
        dex: str,
        alias: str,
        status: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
        access_token: Optional[str] = None,  # opcional: se quiser propagar auth
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/api/episodes/by_vault"
        params = {"dex": dex, "alias": alias, "limit": int(limit), "offset": int(offset)}
        if status:
            params["status"] = status

        headers = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        async with httpx.AsyncClient(timeout=30.0) as cli:
            res = await cli.get(url, params=params, headers=headers)
            data = res.json() if res.content else {}
            if res.status_code >= 400:
                raise RuntimeError(data.get("detail") or data.get("message") or f"signals_error_{res.status_code}")
            return data

    async def link_vault_to_strategy(
        self,
        *,
        chain: str,
        owner: str,
        strategy_id: int,
        dex: str,
        alias: str,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/api/strategies/vault-link"
        payload = {
            "chain": (chain or "").strip().lower(),
            "owner": (owner or "").strip(),
            "strategy_id": int(strategy_id),
            "dex": (dex or "").strip().lower(),
            "alias": (alias or "").strip(),
        }

        async with httpx.AsyncClient(timeout=30.0) as cli:
            res = await cli.post(url, json=payload)
            data = res.json() if res.content else {}
            if res.status_code >= 400:
                raise RuntimeError(data.get("detail") or data.get("message") or f"signals_error_{res.status_code}")
            return data
