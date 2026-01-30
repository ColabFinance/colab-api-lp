from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from web3 import Web3

from adapters.external.database.mongo_client import get_mongo_db
from adapters.external.database.vault_client_registry_repository_mongodb import VaultRegistryRepositoryMongoDB
from adapters.external.database.vault_user_events_repository_mongodb import VaultUserEventsRepositoryMongoDB
from adapters.external.signals.signals_http_client import SignalsHttpClient

from config import get_settings
from core.use_cases.vaults_client_vault_usecase import VaultClientVaultUseCase


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _ms_to_iso(ts_ms: int) -> str:
    try:
        return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _get_nested(d: Dict[str, Any], path: List[str]) -> Any:
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _is_addr(s: Optional[str]) -> bool:
    return isinstance(s, str) and s.startswith("0x") and len(s) == 42


def _checksum(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    t = (s or "").strip()
    if Web3.is_address(t):
        try:
            return Web3.to_checksum_address(t)
        except Exception:
            return t
    return t


def _resolve_vault_address(vault_repo: VaultRegistryRepositoryMongoDB, alias_or_address: str) -> Tuple[str, Optional[str]]:
    key = (alias_or_address or "").strip()
    if not key:
        raise ValueError("alias_or_address is required")

    if _is_addr(key):
        return Web3.to_checksum_address(key), None

    v = vault_repo.find_by_alias(key)
    if not v:
        raise ValueError("Vault not found in vault_registry (unknown alias)")
    return Web3.to_checksum_address(v.address), v.alias


def _modified_dietz_return(
    *,
    start_ms: int,
    end_ms: int,
    end_value_usd: float,
    cashflows: List[Tuple[int, float]],  # (ts_ms, signed_usd) deposits+, withdrawals-
) -> Optional[float]:
    """
    Modified Dietz:
      R = (V1 - V0 - sum(CF)) / (V0 + sum(w_i * CF_i))
    Here we take V0 = 0 (start at first cashflow moment).
    """
    T = float(end_ms - start_ms)
    if T <= 0:
        return None

    sum_cf = 0.0
    denom = 0.0
    for ts, cf in cashflows:
        if ts < start_ms:
            continue
        if ts > end_ms:
            continue
        sum_cf += cf
        w = float(end_ms - ts) / T  # earlier -> bigger weight
        denom += w * cf

    # V0 = 0
    numer = float(end_value_usd) - sum_cf
    if abs(denom) <= 1e-12:
        return None
    return numer / denom


@dataclass
class VaultPerformanceUseCase:
    vault_repo: VaultRegistryRepositoryMongoDB
    user_events_repo: VaultUserEventsRepositoryMongoDB
    signals_client: SignalsHttpClient
    stable_tokens: List[str]

    @classmethod
    def from_settings(cls) -> "VaultPerformanceUseCase":
        db = get_mongo_db()
        vault_repo = VaultRegistryRepositoryMongoDB(db[VaultRegistryRepositoryMongoDB.COLLECTION])
        user_events_repo = VaultUserEventsRepositoryMongoDB(db[VaultUserEventsRepositoryMongoDB.COLLECTION])
        signals_client = SignalsHttpClient.from_settings()

        st = get_settings()
        stable = [x.lower() for x in (st.STABLE_TOKEN_ADDRESSES or []) if isinstance(x, str)]
        return cls(
            vault_repo=vault_repo,
            user_events_repo=user_events_repo,
            signals_client=signals_client,
            stable_tokens=stable,
        )

    def _is_stable_token(self, token_addr: Optional[str]) -> bool:
        if not token_addr:
            return False
        return token_addr.strip().lower() in set(self.stable_tokens or [])

    def _sum_gas_costs_usd(self, events: List[Any]) -> Tuple[float, int]:
        total = 0.0
        cnt = 0
        for ev in events or []:
            try:
                payload = getattr(ev, "payload", None) or {}
                cost = _get_nested(payload, ["gas", "cost_usd"])
                c = _safe_float(cost)
                if c is None:
                    continue
                total += c
                cnt += 1
            except Exception:
                continue
        return float(total), int(cnt)

    async def build_performance(
        self,
        *,
        alias_or_address: str,
        access_token: Optional[str] = None,
        episodes_limit: int = 300,
    ) -> Dict[str, Any]:
        vault_addr, alias_from_registry = _resolve_vault_address(self.vault_repo, alias_or_address)

        v_ent = self.vault_repo.find_by_address(vault_addr)
        v_doc = v_ent.to_mongo() if v_ent else {}
        alias = (v_doc.get("alias") or alias_from_registry or alias_or_address).strip()
        dex = (v_doc.get("dex") or "").strip().lower()

        # --- 1) Episodes from api-signals
        episodes_res = {}
        episodes_items: List[Dict[str, Any]] = []
        episodes_total: Optional[int] = None
        if dex and alias:
            episodes_res = await self.signals_client.list_episodes_by_vault(
                dex=dex,
                alias=alias,
                limit=int(episodes_limit),
                offset=0,
                access_token=access_token,
            )
            episodes_items = list((episodes_res.get("data") or []) if isinstance(episodes_res, dict) else [])
            episodes_total = episodes_res.get("total") if isinstance(episodes_res, dict) else None

        # --- 2) Vault events (api-lp)
        # vault_events = self.vault_events_repo.get_recent_events(dex=dex, alias=alias, kind=None, limit=5000) if dex and alias else []
        # gas_total_usd, gas_cnt = self._sum_gas_costs_usd(vault_events)
        gas_total_usd = 0
        gas_cnt = 0
        
        # --- 3) User cashflows (api-lp)
        # Best-effort: pull a lot (can paginate later)
        user_items = self.user_events_repo.list_by_vault(vault=vault_addr, limit=5000, offset=0)
        # normalize items to dicts
        cashflows: List[Dict[str, Any]] = []
        cashflows_signed: List[Tuple[int, float]] = []

        deposited_usd = 0.0
        withdrawn_usd = 0.0
        missing_usd_count = 0

        for it in user_items or []:
            md = it.to_mongo() if hasattr(it, "to_mongo") else (it if isinstance(it, dict) else {})
            et = (md.get("event_type") or "").strip().lower()
            ts_ms = int(md.get("ts_ms") or md.get("created_at") or 0)
            ts_iso = str(md.get("ts_iso") or md.get("created_at_iso") or _ms_to_iso(ts_ms))

            token = _checksum(md.get("token"))
            amount_human = md.get("amount_human")
            amount_raw = md.get("amount_raw")
            decimals = md.get("decimals")
            tx_hash = str(md.get("tx_hash") or "")

            amt_usd: Optional[float] = None
            usd_src: Optional[str] = None

            # Deposit: if stable token and have amount_human -> USD exact
            if et == "deposit" and self._is_stable_token(token):
                a = _safe_float(amount_human)
                if a is not None:
                    amt_usd = float(a)
                    usd_src = "stable"

            # Withdraw: if transfers include stable token(s), sum (best effort)
            if et == "withdraw" and md.get("transfers"):
                # transfers are raw; without decimals we can't be perfect.
                # If you store decimals later per transfer, you can improve this block.
                # For now: only count if you already store amount_human somewhere (future upgrade).
                pass

            if amt_usd is None:
                missing_usd_count += 1
            else:
                if et == "deposit":
                    deposited_usd += amt_usd
                    cashflows_signed.append((ts_ms, +amt_usd))
                elif et == "withdraw":
                    withdrawn_usd += amt_usd
                    cashflows_signed.append((ts_ms, -amt_usd))

            cashflows.append(
                {
                    "event_type": et,
                    "ts_ms": ts_ms,
                    "ts_iso": ts_iso,
                    "token": token,
                    "amount_human": str(amount_human) if amount_human is not None else None,
                    "amount_raw": str(amount_raw) if amount_raw is not None else None,
                    "decimals": int(decimals) if isinstance(decimals, int) else None,
                    "amount_usd": amt_usd,
                    "amount_usd_source": usd_src or ("unknown" if amt_usd is None else "spot_est"),
                    "tx_hash": tx_hash,
                }
            )

        cashflows.sort(key=lambda x: int(x.get("ts_ms") or 0))

        # --- 4) Current value (live status if available; fallback: last closed episode totals_usd)
        current_value = {
            "total_usd": None,
            "in_position_usd": None,
            "vault_idle_usd": None,
            "fees_uncollected_usd": None,
            "rewards_pending_usd": None,
            "source": "unknown",
        }

        # Try to use your existing status use case if exists
        st = None
        try:
            status_uc = VaultClientVaultUseCase.from_settings()
            # support both sync and async
            if hasattr(status_uc, "get_status"):
                got = status_uc.get_status(alias)  # may be awaitable
                st = (await got) if hasattr(got, "__await__") else got
        except Exception:
            st = None

        if isinstance(st, dict):
            holdings = st.get("holdings") or {}
            totals = holdings.get("totals") or {}
            in_pos = holdings.get("in_position") or {}
            idle = holdings.get("vault_idle") or {}

            current_value["total_usd"] = _safe_float(totals.get("total_usd"))
            current_value["in_position_usd"] = _safe_float(in_pos.get("total_usd"))
            current_value["vault_idle_usd"] = _safe_float(idle.get("total_usd"))
            current_value["fees_uncollected_usd"] = _safe_float(_get_nested(st, ["fees_uncollected", "usd"]))
            current_value["rewards_pending_usd"] = _safe_float(_get_nested(st, ["gauge_rewards", "pending_usd_est"]))
            current_value["source"] = "live_status"
        else:
            # fallback: last CLOSED episode metrics.totals_usd
            last_totals = None
            for ep in episodes_items or []:
                if str(ep.get("status") or "").upper() == "CLOSED":
                    m = ep.get("metrics") or {}
                    last_totals = _safe_float(m.get("totals_usd"))
                    if last_totals is not None:
                        break
            if last_totals is not None:
                current_value["total_usd"] = last_totals
                current_value["source"] = "last_episode"

        # --- 5) Profit (to-date + annualized APR/APY)
        end_value = float(current_value["total_usd"] or 0.0)
        net_contributed = (deposited_usd - withdrawn_usd) if (missing_usd_count == 0 or deposited_usd > 0) else None

        profit_usd = None
        profit_pct = None
        profit_net_gas_usd = None
        profit_net_gas_pct = None

        if deposited_usd > 0:
            profit_usd = (end_value + withdrawn_usd - deposited_usd)
            profit_pct = profit_usd / deposited_usd

            profit_net_gas_usd = profit_usd - float(gas_total_usd or 0.0)
            profit_net_gas_pct = (profit_net_gas_usd / deposited_usd) if deposited_usd > 0 else None

        # Annualized via Modified Dietz (cashflow-aware)
        annual = {"method": "modified_dietz", "days": None, "daily_rate": None, "apr": None, "apy_daily_compound": None}

        if cashflows and (end_value is not None):
            start_ms = int(cashflows[0].get("ts_ms") or 0)
            end_ms = _now_ms()
            days = float(end_ms - start_ms) / 86400000.0 if end_ms > start_ms else 0.0
            
            # only use valued cashflows
            cf = [(ts, amt) for (ts, amt) in cashflows_signed if isinstance(ts, int)]
            R = _modified_dietz_return(start_ms=start_ms, end_ms=end_ms, end_value_usd=end_value, cashflows=cf)
            if R is not None and days > 2:
                daily = (1.0 + float(R)) ** (1.0 / days) - 1.0
                apr = daily * 365.0
                apy = (1.0 + daily) ** 365.0 - 1.0

                annual["days"] = days
                annual["daily_rate"] = daily
                annual["apr"] = apr
                annual["apy_daily_compound"] = apy

        # --- 6) Shape episodes for frontend
        eps = []
        for ep in episodes_items or []:
            eps.append(
                {
                    "id": ep.get("id") or ep.get("_id"),
                    "status": ep.get("status"),
                    "open_time": ep.get("open_time"),
                    "open_time_iso": ep.get("open_time_iso"),
                    "close_time": ep.get("close_time"),
                    "close_time_iso": ep.get("close_time_iso"),
                    "open_price": ep.get("open_price"),
                    "close_price": ep.get("close_price"),
                    "Pa": ep.get("Pa"),
                    "Pb": ep.get("Pb"),
                    "pool_type": ep.get("pool_type"),
                    "mode_on_open": ep.get("mode_on_open"),
                    "majority_on_open": ep.get("majority_on_open"),
                    "last_event_bar": ep.get("last_event_bar"),
                    "metrics": ep.get("metrics"),
                }
            )

        # --- response (front-ready)
        start_iso = cashflows[0]["ts_iso"] if cashflows else None
        out = {
            "vault": {
                "address": vault_addr,
                "alias": alias,
                "dex": dex,
                "chain": v_doc.get("chain"),
                "owner": v_doc.get("owner"),
                "strategy_id": v_doc.get("strategy_id"),
                "config": v_doc.get("config"),
            },
            "period": {
                "start_ts_iso": start_iso,
                "end_ts_iso": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
            "cashflows": cashflows,
            "cashflows_totals": {
                "deposited_usd": deposited_usd if deposited_usd > 0 else None,
                "withdrawn_usd": withdrawn_usd if withdrawn_usd > 0 else None,
                "net_contributed_usd": net_contributed,
                "missing_usd_count": int(missing_usd_count),
            },
            "current_value": current_value,
            "gas_costs": {"total_gas_usd": float(gas_total_usd or 0.0), "tx_count": int(gas_cnt)},
            "profit": {
                "profit_usd": profit_usd,
                "profit_pct": profit_pct,
                "profit_net_gas_usd": profit_net_gas_usd,
                "profit_net_gas_pct": profit_net_gas_pct,
                "annualized": annual,
            },
            "episodes": {"items": eps, "total": episodes_total},
        }
        return out
