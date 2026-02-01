from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from typing import Any, Dict, List, Optional, Tuple

from web3 import Web3

from adapters.external.database.mongo_client import get_mongo_db
from adapters.external.database.vault_client_registry_repository_mongodb import VaultRegistryRepositoryMongoDB
from adapters.external.database.vault_user_events_repository_mongodb import VaultUserEventsRepositoryMongoDB
from adapters.external.market_data.market_data_http_client import MarketDataHttpClient
from adapters.external.signals.signals_http_client import SignalsHttpClient

from config import get_settings
from core.use_cases.vaults_client_vault_usecase import VaultClientVaultUseCase


getcontext().prec = 78


# --- Stablecoin decimals fallback (avoid any pricing/pool lookup for stables)
STABLE_DECIMALS_BY_CHAIN: Dict[str, Dict[str, int]] = {
    "base": {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": 6,  # USDC (Base)
        "0x1c7d4b196cb0c7b01d743fbc6116a902379c7238": 6,  # (your stable list example)
    }
}


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
        w = float(end_ms - ts) / T
        denom += w * cf

    numer = float(end_value_usd) - sum_cf
    if abs(denom) <= 1e-12:
        return None
    return numer / denom


def _raw_to_human_float(amount_raw: Optional[str], decimals: Optional[int]) -> Optional[float]:
    if amount_raw is None or decimals is None:
        return None
    try:
        raw_i = int(str(amount_raw).strip())
        d = int(decimals)
        if d < 0 or d > 255:
            return None
        val = Decimal(raw_i) / (Decimal(10) ** Decimal(d))
        return float(val)
    except Exception:
        return None


@dataclass
class VaultPerformanceUseCase:
    vault_repo: VaultRegistryRepositoryMongoDB
    user_events_repo: VaultUserEventsRepositoryMongoDB
    signals_client: SignalsHttpClient
    market_data: MarketDataHttpClient
    stable_tokens: List[str]

    @classmethod
    def from_settings(cls) -> "VaultPerformanceUseCase":
        db = get_mongo_db()
        vault_repo = VaultRegistryRepositoryMongoDB(db[VaultRegistryRepositoryMongoDB.COLLECTION])
        user_events_repo = VaultUserEventsRepositoryMongoDB(db[VaultUserEventsRepositoryMongoDB.COLLECTION])
        signals_client = SignalsHttpClient.from_settings()
        market_data = MarketDataHttpClient.from_settings()

        st = get_settings()
        stable = [x.strip().lower() for x in (st.STABLE_TOKEN_ADDRESSES or []) if isinstance(x, str) and x.strip()]

        return cls(
            vault_repo=vault_repo,
            user_events_repo=user_events_repo,
            signals_client=signals_client,
            market_data=market_data,
            stable_tokens=stable,
        )

    def _is_stable_token(self, token_addr: Optional[str]) -> bool:
        if not token_addr:
            return False
        return token_addr.strip().lower() in set(self.stable_tokens or [])

    async def _get_decimals_and_price_usd(
        self,
        *,
        chain: str,
        token: str,
        event_price_usd: Optional[str],
        decimals: Optional[int],  # decimals from event/transfer if available
        price_cache: Dict[str, float],
        decimals_cache: Dict[str, int],
    ) -> Tuple[Optional[float], Optional[int], str]:
        """
        Returns (price_usd, decimals, source):
          - stable => price=1.0, decimals resolved, source="stable"
          - if event_price_usd => price from event, decimals resolved, source="event"
          - else market_data => price from spot, decimals resolved, source="spot"
        """
        tk = (token or "").strip()
        if not tk:
            return None, None, "unknown"

        chain_n = (chain or "").strip().lower()
        key = f"{chain_n}:{tk}".lower()

        # --- helper: resolve decimals (event -> cache -> market_data)
        async def _resolve_decimals() -> Optional[int]:
            d_local = STABLE_DECIMALS_BY_CHAIN.get(chain_n, {}).get(tk.lower())
            if d_local is not None:
                return int(d_local)
            
            if decimals is not None:
                try:
                    d = int(decimals)
                    if 0 <= d <= 255:
                        return d
                except Exception:
                    pass

            if key in decimals_cache:
                return int(decimals_cache[key])

            try:
                data = await self.market_data.get_token_price_usd(chain=chain_n, token_address=tk.lower())
                d = data.get("decimals")
                if d is None:
                    return None
                d = int(d)
                if not (0 <= d <= 255):
                    return None
                decimals_cache[key] = d
                return d
            except Exception:
                return None

        # stable path: price is 1, but decimals still needed
        if self._is_stable_token(tk):
            d = await _resolve_decimals()
            return 1.0, d, "stable"

        # event price path
        if event_price_usd is not None and str(event_price_usd).strip() != "":
            p = _safe_float(event_price_usd)
            d = await _resolve_decimals()
            if p is not None and d is not None:
                return float(p), int(d), "event"

        # cached spot price
        if key in price_cache:
            d = await _resolve_decimals()
            if d is None:
                return None, None, "unknown"
            return float(price_cache[key]), int(d), "spot"

        # market_data spot
        try:
            data = await self.market_data.get_token_price_usd(chain=chain_n, token_address=tk.lower())
            px = data.get("price_usd")
            p = _safe_float(px)
            d = await _resolve_decimals()
            if p is None or d is None:
                return None, None, "unknown"
            price_cache[key] = float(p)
            return float(p), int(d), "spot"
        except Exception:
            return None, None, "unknown"

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
        chain = (v_doc.get("chain") or "").strip().lower()

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

        # --- 2) Vault events (gas) [kept as-is]
        gas_total_usd = 0
        gas_cnt = 0

        # --- 3) User cashflows
        user_items = self.user_events_repo.list_by_vault(vault=vault_addr, limit=5000, offset=0)

        cashflows: List[Dict[str, Any]] = []
        cashflows_signed: List[Tuple[int, float]] = []

        deposited_usd = 0.0
        withdrawn_usd = 0.0
        missing_usd_count = 0

        # per-request, in-memory (NOT persisted cache)
        price_cache: Dict[str, float] = {}
        decimals_cache: Dict[str, int] = {}

        for it in user_items or []:
            md = it.to_mongo() if hasattr(it, "to_mongo") else (it if isinstance(it, dict) else {})
            et = (md.get("event_type") or "").strip().lower()
            ts_ms = int(md.get("ts_ms") or md.get("created_at") or 0)
            ts_iso = str(md.get("ts_iso") or md.get("created_at_iso") or _ms_to_iso(ts_ms))
            tx_hash = str(md.get("tx_hash") or "")

            if et == "deposit":
                token = _checksum(md.get("token"))
                amount_human = md.get("amount_human")
                amount_raw = md.get("amount_raw")
                decimals = md.get("decimals")
                token_price_usd = md.get("token_price_usd")

                price, resolved_decimals, src = await self._get_decimals_and_price_usd(
                    chain=chain or (md.get("chain") or "").strip().lower(),
                    token=token or "",
                    event_price_usd=token_price_usd,
                    decimals=md.get("decimals"),
                    price_cache=price_cache,
                    decimals_cache=decimals_cache,
                )

                amt_h = _safe_float(amount_human)
                if amt_h is None:
                    amt_h = _raw_to_human_float(amount_raw, resolved_decimals)

                amt_usd: Optional[float] = None
                usd_src: Optional[str] = None

                if amt_h is not None and price is not None:
                    amt_usd = float(amt_h) * float(price)
                    usd_src = src
                    deposited_usd += amt_usd
                    cashflows_signed.append((ts_ms, +amt_usd))
                else:
                    missing_usd_count += 1

                cashflows.append(
                    {
                        "event_type": "deposit",
                        "ts_ms": ts_ms,
                        "ts_iso": ts_iso,
                        "token": token,
                        "amount_human": str(amount_human) if amount_human is not None else (str(amt_h) if amt_h is not None else None),
                        "amount_raw": str(amount_raw) if amount_raw is not None else None,
                        "decimals": int(resolved_decimals) if isinstance(resolved_decimals, int) else None,
                        "amount_usd": amt_usd,
                        "amount_usd_source": usd_src or "unknown",
                        "tx_hash": tx_hash,
                    }
                )

            elif et == "withdraw":
                transfers = md.get("transfers") or []
                if not transfers:
                    missing_usd_count += 1
                    cashflows.append(
                        {
                            "event_type": "withdraw",
                            "ts_ms": ts_ms,
                            "ts_iso": ts_iso,
                            "token": None,
                            "amount_human": None,
                            "amount_raw": None,
                            "decimals": None,
                            "amount_usd": None,
                            "amount_usd_source": "unknown",
                            "tx_hash": tx_hash,
                        }
                    )
                    continue

                # one cashflow entry per transfer (multi-token withdraw)
                for tr in transfers:
                    token = _checksum((tr.get("token") if isinstance(tr, dict) else None) or "")
                    amount_raw = (tr.get("amount_raw") if isinstance(tr, dict) else None)
                    decimals = (tr.get("decimals") if isinstance(tr, dict) else None)
                    amount_human = (tr.get("amount_human") if isinstance(tr, dict) else None)
                    price_usd = (tr.get("price_usd") if isinstance(tr, dict) else None)

                    price, resolved_decimals, src = await self._get_decimals_and_price_usd(
                        chain=chain or (md.get("chain") or "").strip().lower(),
                        token=token or "",
                        event_price_usd=price_usd,
                        decimals=decimals,
                        price_cache=price_cache,
                        decimals_cache=decimals_cache,
                    )

                    print("price, decimals, src",price, decimals, src)
                    
                    amt_h = _safe_float(amount_human)
                    if amt_h is None:
                        amt_h = _raw_to_human_float(amount_raw, resolved_decimals)
                        
                    amt_usd: Optional[float] = None
                    usd_src: Optional[str] = None

                    if amt_h is not None and price is not None:
                        amt_usd = float(amt_h) * float(price)
                        usd_src = src
                        withdrawn_usd += amt_usd
                        cashflows_signed.append((ts_ms, -amt_usd))
                    else:
                        missing_usd_count += 1

                    cashflows.append(
                        {
                            "event_type": "withdraw",
                            "ts_ms": ts_ms,
                            "ts_iso": ts_iso,
                            "token": token,
                            "amount_human": str(amount_human) if amount_human is not None else (str(amt_h) if amt_h is not None else None),
                            "amount_raw": str(amount_raw) if amount_raw is not None else None,
                            "decimals": int(resolved_decimals) if isinstance(resolved_decimals, int) else None,
                            "amount_usd": amt_usd,
                            "amount_usd_source": usd_src or "unknown",
                            "tx_hash": tx_hash,
                        }
                    )
            else:
                # ignore unknown types but keep transparency
                continue

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

        st = None
        try:
            status_uc = VaultClientVaultUseCase.from_settings()
            if hasattr(status_uc, "get_status"):
                got = status_uc.get_status(alias)
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
        net_contributed = (deposited_usd - withdrawn_usd)

        profit_usd = None
        profit_pct = None
        profit_net_gas_usd = None
        profit_net_gas_pct = None

        if deposited_usd > 0:
            profit_usd = (end_value + withdrawn_usd - deposited_usd)
            profit_pct = profit_usd / deposited_usd

            profit_net_gas_usd = profit_usd - float(gas_total_usd or 0.0)
            profit_net_gas_pct = (profit_net_gas_usd / deposited_usd) if deposited_usd > 0 else None

        annual = {"method": "modified_dietz", "days": None, "daily_rate": None, "apr": None, "apy_daily_compound": None}

        if cashflows and (end_value is not None):
            start_ms = int(cashflows[0].get("ts_ms") or 0)
            end_ms = _now_ms()
            days = float(end_ms - start_ms) / 86400000.0 if end_ms > start_ms else 0.0

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
