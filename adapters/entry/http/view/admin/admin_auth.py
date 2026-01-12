from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Optional, Set

import requests
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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


_jwks_cache: Dict[str, Any] = {"ts": 0, "jwks": None}


def _get_jwks() -> Dict[str, Any]:
    s = get_settings()
    now = int(time.time())

    # Cache for 10 minutes
    if _jwks_cache["jwks"] and (now - int(_jwks_cache["ts"])) < 600:
        return _jwks_cache["jwks"]

    r = requests.get(s.PRIVY_JWKS_URL, timeout=10)
    if r.status_code != 200:
        raise HTTPException(status_code=503, detail="Failed to fetch JWKS for token verification.")

    jwks = r.json()
    _jwks_cache["jwks"] = jwks
    _jwks_cache["ts"] = now
    return jwks


def _select_jwk(jwks: Dict[str, Any], kid: str) -> Optional[Dict[str, Any]]:
    for k in jwks.get("keys", []):
        if k.get("kid") == kid:
            return k
    return None


def _extract_wallet_from_claims(claims: Dict[str, Any]) -> str:
    """
    Best-effort extraction:
    - Prefer a direct wallet claim if present.
    - Otherwise, fallback to empty string.

    NOTE: You may want to customize this to match the exact claims structure
    you rely on (e.g. embedded wallet address, linked wallets, etc.).
    """
    # Common patterns in JWT payloads across providers:
    for key in ["wallet_address", "address", "wallet", "user_wallet"]:
        v = claims.get(key)
        if isinstance(v, str) and v.startswith("0x"):
            return v
    return ""


def require_admin(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> AdminPrincipal:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization bearer token.")

    token = creds.credentials
    s = get_settings()

    try:
        headers = jwt.get_unverified_header(token)
        kid = headers.get("kid")
        if not kid:
            raise HTTPException(status_code=401, detail="Invalid token header (missing kid).")

        jwks = _get_jwks()
        jwk = _select_jwk(jwks, kid)
        if not jwk:
            raise HTTPException(status_code=401, detail="Unknown token key (kid not found).")

        key = jwt.algorithms.ECAlgorithm.from_jwk(jwk)

        claims = jwt.decode(
            token,
            key=key,
            algorithms=["ES256"],
            audience=s.PRIVY_APP_ID,
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )

        if claims.get("iss") != "privy.io":
            raise HTTPException(status_code=401, detail="Invalid token issuer.")

        privy_did = str(claims.get("sub") or "")
        wallet = _extract_wallet_from_claims(claims).lower()

        # If wallet isn't in claims, you can enforce a different rule here.
        # For now: require it.
        if not wallet:
            raise HTTPException(status_code=403, detail="Token missing wallet address claim.")

        if wallet not in _admin_allowlist():
            raise HTTPException(status_code=403, detail="Not authorized (wallet not allowlisted).")

        return AdminPrincipal(privy_did=privy_did, wallet_address=wallet)

    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication failed.")
