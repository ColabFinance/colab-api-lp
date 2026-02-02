from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Any, Dict, List, Optional, Set, Tuple

from web3 import Web3
from eth_utils import keccak

from adapters.external.database.mongo_client import get_mongo_db
from adapters.external.database.vault_client_registry_repository_mongodb import VaultRegistryRepositoryMongoDB
from adapters.external.database.vault_user_events_repository_mongodb import VaultUserEventsRepositoryMongoDB

from adapters.external.market_data.market_data_http_client import MarketDataHttpClient
from config import get_settings
from core.domain.entities.vault_user_event_entity import VaultUserEventEntity, VaultUserEventTransfer


getcontext().prec = 78

_TRANSFER_TOPIC0 = "0x" + keccak(text="Transfer(address,address,uint256)").hex()


def _is_address_like(s: str) -> bool:
    return isinstance(s, str) and s.startswith("0x") and len(s) == 42


def _norm(s: Optional[str]) -> Optional[str]:
    v = (s or "").strip()
    return v or None


def _checksum_if_addr(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    t = s.strip()
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

    if _is_address_like(key):
        return Web3.to_checksum_address(key), None

    v = vault_repo.find_by_alias(key)
    if not v:
        raise ValueError("Vault not found in vault_registry (unknown alias)")
    return Web3.to_checksum_address(v.address), v.alias


def _parse_erc20_transfers_from_receipt(
    receipt: Dict[str, Any],
    *,
    token_allowlist: List[str],
) -> List[VaultUserEventTransfer]:
    logs = receipt.get("logs") or []
    allow = set()
    for t in token_allowlist or []:
        if Web3.is_address(t):
            allow.add(Web3.to_checksum_address(t))

    out: List[VaultUserEventTransfer] = []
    for lg in logs:
        try:
            addr = lg.get("address")
            if not addr or not Web3.is_address(addr):
                continue
            token = Web3.to_checksum_address(addr)
            if allow and token not in allow:
                continue

            topics = lg.get("topics") or []
            if not topics or str(topics[0]).lower() != _TRANSFER_TOPIC0.lower():
                continue
            if len(topics) < 3:
                continue

            t1 = str(topics[1])
            t2 = str(topics[2])

            from_addr = "0x" + t1[-40:]
            to_addr = "0x" + t2[-40:]
            if Web3.is_address(from_addr):
                from_addr = Web3.to_checksum_address(from_addr)
            if Web3.is_address(to_addr):
                to_addr = Web3.to_checksum_address(to_addr)

            data_hex = lg.get("data") or "0x0"
            if not isinstance(data_hex, str) or not data_hex.startswith("0x"):
                continue
            amount = int(data_hex, 16)

            out.append(
                VaultUserEventTransfer(
                    token=token,
                    **{"from": from_addr, "to": to_addr},
                    amount_raw=str(amount),
                )
            )
        except Exception:
            continue

    return out


def _sum_transfers(
    transfers: List[VaultUserEventTransfer],
    *,
    from_addr: Optional[str] = None,
    to_addr: Optional[str] = None,
    token: Optional[str] = None,
) -> int:
    fa = _checksum_if_addr(from_addr)
    ta = _checksum_if_addr(to_addr)
    tk = _checksum_if_addr(token)

    s = 0
    for t in transfers or []:
        if tk and _checksum_if_addr(t.token) != tk:
            continue
        if fa and _checksum_if_addr(t.from_addr) != fa:
            continue
        if ta and _checksum_if_addr(t.to_addr) != ta:
            continue
        try:
            s += int(t.amount_raw)
        except Exception:
            continue
    return s


def _raw_to_human_str(amount_raw: Optional[str], decimals: Optional[int]) -> Optional[str]:
    if amount_raw is None or decimals is None:
        return None
    try:
        raw_i = int(str(amount_raw).strip())
        if raw_i == 0:
            return "0"
        d = int(decimals)
        if d < 0 or d > 255:
            return None
        scale = Decimal(10) ** Decimal(-d)
        val = (Decimal(raw_i) * scale)
        s = format(val, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s
    except Exception:
        return None


def _extract_token_meta_from_pricing(pricing: Dict[str, Any], *, token_address: str) -> Dict[str, Any]:
    """
    This function is defensive because your pricing endpoint might include extra fields in real life.
    We try multiple common keys for decimals/symbol.
    """
    out: Dict[str, Any] = {}

    # decimals
    dec = pricing.get("decimals")
    if dec is None:
        dec = pricing.get("token_decimals")
    if dec is None:
        dec = pricing.get("token0_decimals")
    if dec is None:
        dec = pricing.get("token1_decimals")

    try:
        if dec is not None:
            out["decimals"] = int(dec)
    except Exception:
        pass

    # symbol
    sym = pricing.get("symbol")
    if sym is None:
        sym = pricing.get("token_symbol")
    if sym is None:
        sym = pricing.get("token0_symbol")
    if sym is None:
        sym = pricing.get("token1_symbol")

    if isinstance(sym, str) and sym.strip():
        out["symbol"] = sym.strip()

    # price
    px = pricing.get("price_usd")
    if px is not None:
        out["price_usd"] = str(px)

    return out


def _filter_payout_transfers(
    transfers: List[VaultUserEventTransfer],
    *,
    payout_to: str,
    payout_from: Optional[str] = None,
) -> List[VaultUserEventTransfer]:
    to_c = _checksum_if_addr(payout_to)
    from_c = _checksum_if_addr(payout_from) if payout_from else None

    out: List[VaultUserEventTransfer] = []
    for t in transfers or []:
        try:
            if to_c and _checksum_if_addr(t.to_addr) != to_c:
                continue
            if from_c and _checksum_if_addr(t.from_addr) != from_c:
                continue
            out.append(t)
        except Exception:
            continue
    return out


@dataclass
class VaultUserEventsUseCase:
    vault_repo: VaultRegistryRepositoryMongoDB
    events_repo: VaultUserEventsRepositoryMongoDB
    market_data: MarketDataHttpClient
    stable_tokens: Set[str]

    @classmethod
    def from_settings(cls) -> "VaultUserEventsUseCase":
        db = get_mongo_db()
        vault_repo = VaultRegistryRepositoryMongoDB(db[VaultRegistryRepositoryMongoDB.COLLECTION])
        events_repo = VaultUserEventsRepositoryMongoDB(db[VaultUserEventsRepositoryMongoDB.COLLECTION])
        events_repo.ensure_indexes()

        st = get_settings()
        market_data = MarketDataHttpClient.from_settings()
        stable_tokens = set([x.strip().lower() for x in (st.STABLE_TOKEN_ADDRESSES or []) if x])

        return cls(
            vault_repo=vault_repo,
            events_repo=events_repo,
            market_data=market_data,
            stable_tokens=stable_tokens,
        )

    def _is_stable(self, token_addr: Optional[str]) -> bool:
        if not token_addr:
            return False
        return token_addr.strip().lower() in self.stable_tokens

    async def _try_get_price_usd(self, *, chain: str, token_address: str) -> Optional[str]:
        """
        Best-effort:
        - if stable -> None (skip external call)
        - else tries api-market-data and returns price_usd as string
        """
        token_l = (token_address or "").strip().lower()
        if not token_l or not token_l.startswith("0x") or len(token_l) != 42:
            return None

        if self._is_stable(token_l):
            return None

        try:
            data = await self.market_data.get_token_price_usd(chain=chain, token_address=token_l)
            px = data.get("price_usd")
            if px is None:
                return None
            return str(px)
        except Exception:
            return None

    async def _try_get_pricing_details(self, *, chain: str, token_address: str) -> Dict[str, Any]:
        """
        Best-effort pricing+meta.
        - stable tokens: force price_usd=1 (but we still try calling market-data to get decimals/symbol if it returns them)
        - non-stable: take price_usd from market-data
        """
        token_l = (token_address or "").strip().lower()
        if not token_l or not token_l.startswith("0x") or len(token_l) != 42:
            return {}

        is_stable = self._is_stable(token_l)
        base: Dict[str, Any] = {}
        if is_stable:
            base["price_usd"] = "1"

        try:
            data = await self.market_data.get_token_price_usd(chain=(chain or "").strip().lower(), token_address=token_l)
            if isinstance(data, dict):
                out = dict(data)
                # force stable price=1
                if is_stable:
                    out["price_usd"] = "1"
                # merge base keys if missing
                for k, v in base.items():
                    out.setdefault(k, v)
                return out
        except Exception:
            return base

        return base

    async def record_deposit(
        self,
        *,
        alias_or_address: str,
        chain: str,
        dex: Optional[str],
        owner: Optional[str],
        token: str,
        amount_human: Optional[str],
        amount_raw: Optional[str],
        decimals: Optional[int],
        tx_hash: str,
        receipt: Optional[Dict[str, Any]],
        from_addr: Optional[str],
        to_addr: Optional[str],
    ) -> VaultUserEventEntity:
        vault, alias = _resolve_vault_address(self.vault_repo, alias_or_address)

        token_c = _checksum_if_addr(token)
        if not token_c or not Web3.is_address(token_c):
            raise ValueError("Invalid token address")

        rcpt = receipt or {}
        block_number = rcpt.get("blockNumber")
        try:
            block_number = int(block_number) if block_number is not None else None
        except Exception:
            block_number = None

        transfers: List[VaultUserEventTransfer] = []
        if rcpt:
            transfers = _parse_erc20_transfers_from_receipt(rcpt, token_allowlist=[token_c])

        if (amount_raw is None or str(amount_raw).strip() == "") and transfers:
            inferred = _sum_transfers(
                transfers,
                from_addr=from_addr or owner,
                to_addr=to_addr or vault,
                token=token_c,
            )
            if inferred > 0:
                amount_raw = str(inferred)

        # If decimals missing but we have raw, try to get decimals from pricing (as you requested)
        dec_i: Optional[int] = int(decimals) if decimals is not None else None
        if dec_i is None and amount_raw:
            pricing = await self._try_get_pricing_details(chain=(chain or "").strip().lower(), token_address=token_c)
            meta = _extract_token_meta_from_pricing(pricing, token_address=token_c)
            if isinstance(meta.get("decimals"), int):
                dec_i = int(meta["decimals"])

        # If human missing, infer from raw+decimals
        human_s = _norm(amount_human)
        if human_s is None:
            inferred_h = _raw_to_human_str(amount_raw, dec_i)
            if inferred_h is not None:
                human_s = inferred_h

        token_price_usd = await self._try_get_price_usd(chain=(chain or "").strip().lower(), token_address=token_c)

        ent = VaultUserEventEntity(
            vault=vault,
            alias=alias,
            chain=(chain or "").strip().lower(),
            dex=_norm(dex),
            event_type="deposit",
            owner=_checksum_if_addr(owner),
            token=token_c,
            amount_human=human_s,
            amount_raw=_norm(amount_raw),
            decimals=dec_i,
            token_price_usd=token_price_usd,
            tx_hash=(tx_hash or "").strip(),
            block_number=block_number,
            transfers=transfers or None,
        )
        return self.events_repo.upsert_idempotent(ent)

    async def record_withdraw(
        self,
        *,
        alias_or_address: str,
        chain: str,
        dex: Optional[str],
        owner: Optional[str],
        to: str,
        tx_hash: str,
        receipt: Optional[Dict[str, Any]],
        token_addresses: List[str],
    ) -> VaultUserEventEntity:
        vault, alias = _resolve_vault_address(self.vault_repo, alias_or_address)

        to_c = _checksum_if_addr(to)
        if not to_c or not Web3.is_address(to_c):
            raise ValueError("Invalid withdraw destination (to)")

        rcpt = receipt or {}
        block_number = rcpt.get("blockNumber")
        try:
            block_number = int(block_number) if block_number is not None else None
        except Exception:
            block_number = None

        allow: List[str] = []
        for t in token_addresses or []:
            tc = _checksum_if_addr(t)
            if tc and Web3.is_address(tc):
                allow.append(tc)

        all_transfers: List[VaultUserEventTransfer] = []
        if rcpt and allow:
            all_transfers = _parse_erc20_transfers_from_receipt(rcpt, token_allowlist=allow)

        payout_transfers = _filter_payout_transfers(
            all_transfers,
            payout_to=to_c,
            payout_from=vault,
        )
            
        # Enrich each transfer with: decimals, symbol, price_usd, amount_human (if missing)
        chain_n = (chain or "").strip().lower()
        if payout_transfers:
            unique_tokens = sorted({(tr.token or "").strip() for tr in payout_transfers if tr.token})
            pricing_by_token: Dict[str, Dict[str, Any]] = {}

            for tk in unique_tokens:
                pricing_by_token[tk] = await self._try_get_pricing_details(chain=chain_n, token_address=tk)

            for tr in payout_transfers:
                pr = pricing_by_token.get(tr.token) or {}
                meta = _extract_token_meta_from_pricing(pr, token_address=tr.token)

                # decimals / symbol
                if tr.decimals is None and isinstance(meta.get("decimals"), int):
                    tr.decimals = int(meta["decimals"])
                if tr.symbol is None and isinstance(meta.get("symbol"), str):
                    tr.symbol = meta["symbol"]

                # price_usd:
                # - stable: ensure "1"
                # - non-stable: use pricing price_usd if present
                if self._is_stable(tr.token):
                    tr.price_usd = "1"
                else:
                    if tr.price_usd is None and meta.get("price_usd") is not None:
                        tr.price_usd = str(meta["price_usd"])

                # amount_human
                if getattr(tr, "amount_human", None) is None:
                    inferred_h = _raw_to_human_str(tr.amount_raw, tr.decimals)
                    if inferred_h is not None:
                        tr.amount_human = inferred_h

        ent = VaultUserEventEntity(
            vault=vault,
            alias=alias,
            chain=(chain or "").strip().lower(),
            dex=_norm(dex),
            event_type="withdraw",
            owner=_checksum_if_addr(owner),
            to=to_c,
            tx_hash=(tx_hash or "").strip(),
            block_number=block_number,
            transfers=payout_transfers or None,
        )
        return self.events_repo.upsert_idempotent(ent)

    def list_events(self, *, alias_or_address: str, limit: int, offset: int) -> Dict[str, Any]:
        vault, _alias = _resolve_vault_address(self.vault_repo, alias_or_address)
        limit_i = int(limit or 50)
        offset_i = int(offset or 0)
        if limit_i < 1:
            limit_i = 1
        if limit_i > 200:
            limit_i = 200
        if offset_i < 0:
            offset_i = 0

        items = self.events_repo.list_by_vault(vault=vault, limit=limit_i, offset=offset_i)
        total = self.events_repo.count_by_vault(vault=vault)
        return {"items": items, "total": total}
