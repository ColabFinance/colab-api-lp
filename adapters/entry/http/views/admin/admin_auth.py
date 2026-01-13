from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional, Set

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from privy import PrivyAPI

from config import get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AdminPrincipal:
    """
    Authenticated admin identity derived from a Privy access token.
    """
    privy_did: str
    wallet_address: str


@lru_cache(maxsize=1)
def _admin_allowlist() -> Set[str]:
    s = get_settings()
    return {x.strip().lower() for x in (s.ADMIN_WALLETS or "").split(",") if x.strip()}


@lru_cache(maxsize=1)
def _privy_client() -> PrivyAPI:
    s = get_settings()
    if not getattr(s, "PRIVY_APP_ID", None):
        raise RuntimeError("Missing settings.PRIVY_APP_ID")
    if not getattr(s, "PRIVY_APP_SECRET", None):
        raise RuntimeError("Missing settings.PRIVY_APP_SECRET")

    # app_secret = Privy API Key (dashboard)
    return PrivyAPI(app_id=s.PRIVY_APP_ID, app_secret=s.PRIVY_APP_SECRET)


def _extract_wallet_from_privy_user(user: Any) -> str:
    """
    Extracts an Ethereum address from a Privy "user" object/dict.

    We check common SDK shapes:
      - user.linked_accounts: [{type:"wallet", address:"0x..."}, ...]
      - user.wallet: {address:"0x..."}
      - user.wallets: [{address:"0x..."}, ...]
    """
    def get(obj: Any, key: str) -> Any:
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    # 1) direct-ish
    for key in ["wallet_address", "address"]:
        v = get(user, key)
        if isinstance(v, str) and v.startswith("0x"):
            return v

    # 2) wallet object
    wallet_obj = get(user, "wallet")
    addr = get(wallet_obj, "address") or get(wallet_obj, "wallet_address")
    if isinstance(addr, str) and addr.startswith("0x"):
        return addr

    # 3) wallets array
    wallets = get(user, "wallets")
    if isinstance(wallets, list):
        for w in wallets:
            addr = get(w, "address") or get(w, "wallet_address")
            if isinstance(addr, str) and addr.startswith("0x"):
                return addr

    # 4) linked accounts
    linked = get(user, "linked_accounts")
    if isinstance(linked, list):
        for acc in linked:
            # Privy usually tags wallets like: type="wallet"
            acc_type = (get(acc, "type") or "").lower()
            addr = get(acc, "address") or get(acc, "wallet_address")
            if acc_type == "wallet" and isinstance(addr, str) and addr.startswith("0x"):
                return addr
            # fallback: if it looks like an address, accept
            if isinstance(addr, str) and addr.startswith("0x"):
                return addr

    return ""


def _get_user_by_did(client: PrivyAPI, did: str) -> Any:
    """
    The SDK shape can differ by version. We try the common patterns.

    If your installed privy SDK exposes only one of these methods, the others
    will raise AttributeError and we'll fallback.
    """
    users = client.users

    # common: users.get(did)
    fn = getattr(users, "get", None)
    if callable(fn):
        return fn(did)

    # common: users.get_by_id(user_id=did)
    fn = getattr(users, "get_by_id", None)
    if callable(fn):
        return fn(user_id=did)

    # common: users.retrieve(user_id=did)
    fn = getattr(users, "retrieve", None)
    if callable(fn):
        return fn(user_id=did)

    raise RuntimeError("Privy SDK does not expose a method to fetch user by DID (users.get/get_by_id/retrieve).")


def require_admin(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> AdminPrincipal:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization bearer token.")

    token = creds.credentials

    try:
        client = _privy_client()

        claims = client.users.verify_access_token(auth_token=token)

        # claims can be dict-like
        privy_did = ""
        if isinstance(claims, dict):
            privy_did = str(claims.get("user_id") or "")
        else:
            privy_did = str(getattr(claims, "user_id", "") or "")

        if not privy_did:
            raise HTTPException(status_code=401, detail="Invalid token (missing user_id).")

        user = _get_user_by_did(client, privy_did)
        wallet = _extract_wallet_from_privy_user(user).lower()

        if not wallet:
            raise HTTPException(status_code=403, detail="Token verified but user has no linked wallet address.")

        if wallet not in _admin_allowlist():
            raise HTTPException(status_code=403, detail="Not authorized (wallet not allowlisted).")

        return AdminPrincipal(privy_did=privy_did, wallet_address=wallet)

    except HTTPException:
        raise
    except Exception as e:
        msg = str(e) or "Invalid token"
        low = msg.lower()
        if "invalid" in low or "expired" in low or "auth token" in low:
            raise HTTPException(status_code=401, detail=msg)
        raise HTTPException(status_code=401, detail=f"Authentication failed: {msg}")
