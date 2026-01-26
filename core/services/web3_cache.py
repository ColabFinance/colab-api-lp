# core/services/web3_cache.py

from __future__ import annotations

from time import time
from typing import Dict, Tuple

from web3 import Web3
from web3.providers.rpc import HTTPProvider

_W3_CACHE: Dict[str, Tuple[float, Web3]] = {}
_W3_TTL_SEC = 10 * 60  # 10 minutes


def get_web3(rpc_url: str) -> Web3:
    """
    Cache Web3 instances per rpc_url to avoid rebuilding HTTPProvider each request.
    """
    url = (rpc_url or "").strip()
    if not url:
        raise ValueError("rpc_url is required")

    now = time()
    hit = _W3_CACHE.get(url)
    if hit and (now - hit[0]) < _W3_TTL_SEC:
        return hit[1]

    w3 = Web3(HTTPProvider(url, request_kwargs={"timeout": 30}))
    _W3_CACHE[url] = (now, w3)
    return w3
