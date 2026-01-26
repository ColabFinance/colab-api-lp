from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from time import perf_counter, time
from typing import Dict, List, Tuple, Optional, Any

from hexbytes import HexBytes
import requests
from web3 import Web3
from web3.contract import Contract

from config import get_settings
from adapters.chain.client_vault import ClientVaultAdapter
from core.domain.schemas.onchain_types import (
    Erc20Meta,
    FeesUncollectedOut,
    GaugeRewardBalancesOut,
    GaugeRewardsOut,
    HoldingsBlock,
    HoldingsOut,
    PriceBlock,
    PricesOut,
    VaultStatusOut,
)

getcontext().prec = 90
Q96 = Decimal(2) ** 96
U128_MAX = (1 << 128) - 1
ZERO_ADDR = "0x0000000000000000000000000000000000000000"

USD_SYMBOLS = {"USDC", "USDT", "DAI", "USD+", "USDB", "USDE"}

# ----------------- caches -----------------

_TOKEN_META_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_TOKEN_META_TTL_SEC = 24 * 60 * 60

_VAULT_STATIC_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_VAULT_STATIC_TTL_SEC = 10 * 60  # 10 minutes

# short TTL caches for heavy read blocks
_NFPM_POS_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_NFPM_POS_TTL_SEC = 60  # ticks/liquidity rarely change (rebalance/mint/burn)

_NFPM_COLLECT_PREVIEW_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_NFPM_COLLECT_PREVIEW_TTL_SEC = 5  # changes with fees, but can be short cached

_NFT_OWNER_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_NFT_OWNER_TTL_SEC = 60

_ERC20_BAL_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_ERC20_BAL_TTL_SEC = 3

# Pancake reward token cache (CAKE() per MasterChef)
_GAUGE_REWARD_TOKEN_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_GAUGE_REWARD_TOKEN_TTL_SEC = 24 * 60 * 60

# V3 pool meta + slot0 caches (for CAKE/USDC price)
_V3_POOL_META_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_V3_POOL_META_TTL_SEC = 24 * 60 * 60

_V3_POOL_SLOT0_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_V3_POOL_SLOT0_TTL_SEC = 15


def _cache_get(cache: Dict[str, Tuple[float, Dict[str, Any]]], key: str, ttl: int) -> Optional[Dict[str, Any]]:
    hit = cache.get(key)
    if not hit:
        return None
    ts, val = hit
    if (time() - ts) > ttl:
        return None
    return val


def _cache_set(cache: Dict[str, Tuple[float, Dict[str, Any]]], key: str, val: Dict[str, Any]) -> None:
    cache[key] = (time(), val)
    

def _to_checksum(addr_any: Any) -> str:
    if addr_any is None:
        return ZERO_ADDR
    if isinstance(addr_any, str) and addr_any.startswith("0x") and len(addr_any) == 42:
        try:
            return Web3.to_checksum_address(addr_any)
        except Exception:
            return addr_any
    if isinstance(addr_any, (bytes, bytearray, HexBytes)):
        hx = "0x" + bytes(addr_any).hex()[-40:]
        try:
            return Web3.to_checksum_address(hx)
        except Exception:
            return hx
    s = str(addr_any)
    if s.startswith("0x") and len(s) == 42:
        try:
            return Web3.to_checksum_address(s)
        except Exception:
            return s
    return s

 
@dataclass
class _CallSpec:
    to: str
    data: str
    out_types: List[str]


def _enc(contract: Contract, fn: str, args: Optional[list] = None) -> str:
    """
    web3.py v7: contract.encode_abi(abi_element_identifier=..., args=...)
    web3.py <=6: contract.encodeABI(fn_name=..., args=...)
    """
    args = args or []
    if hasattr(contract, "encode_abi"):
        # v7+
        return contract.encode_abi(abi_element_identifier=fn, args=args)
    # legacy
    return contract.encodeABI(fn_name=fn, args=args)


ABI_ERC20 = [
    {"name": "decimals", "outputs": [{"type": "uint8"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "symbol", "outputs": [{"type": "string"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "balanceOf", "outputs": [{"type": "uint256"}], "inputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

ABI_NFPM = [
    {
        "name": "positions",
        "inputs": [{"type": "uint256", "name": "tokenId"}],
        "outputs": [
            {"type": "uint96"},   # nonce
            {"type": "address"},  # operator
            {"type": "address"},  # token0
            {"type": "address"},  # token1
            {"type": "uint24"},   # fee
            {"type": "int24"},    # tickLower
            {"type": "int24"},    # tickUpper
            {"type": "uint128"},  # liquidity
            {"type": "uint256"},  # feeGrowthInside0LastX128
            {"type": "uint256"},  # feeGrowthInside1LastX128
            {"type": "uint128"},  # tokensOwed0
            {"type": "uint128"},  # tokensOwed1
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "collect",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "recipient", "type": "address"},
                    {"name": "amount0Max", "type": "uint128"},
                    {"name": "amount1Max", "type": "uint128"},
                ],
            }
        ],
        "outputs": [{"type": "uint256", "name": "amount0"}, {"type": "uint256", "name": "amount1"}],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "name": "ownerOf",
        "inputs": [{"type": "uint256", "name": "tokenId"}],
        "outputs": [{"type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Generic gauge style (Aerodrome-like): earned(account, tokenId) + rewardToken()
ABI_GAUGE_MIN = [
    {
        "name": "earned",
        "inputs": [{"type": "address", "name": "account"}, {"type": "uint256", "name": "tokenId"}],
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {"name": "rewardToken", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

# Pancake MasterChefV3 minimal: pendingCake(tokenId) + CAKE()
ABI_PANCAKE_MASTERCHEF_MIN = [
    {"name": "pendingCake", "inputs": [{"type": "uint256", "name": "tokenId"}], "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"name": "CAKE", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

# V3 pool minimal for CAKE/USDC reference
ABI_V3_POOL_MIN = [
    {"name": "token0", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token1", "outputs": [{"type": "address"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {
        "name": "slot0",
        "inputs": [],
        "outputs": [
            {"type": "uint160"},  # sqrtPriceX96
            {"type": "int24"},    # tick
            {"type": "uint16"},   # observationIndex
            {"type": "uint16"},   # observationCardinality
            {"type": "uint16"},   # observationCardinalityNext
            {"type": "uint32"},   # feeProtocol  <-- FIX (was uint8)
            {"type": "bool"},     # unlocked
        ],
        "stateMutability": "view",
        "type": "function",
    },
]



# ----------------- helpers -----------------

def _is_usd_symbol(sym: str) -> bool:
    return (sym or "").upper() in USD_SYMBOLS


def _is_stable_addr(addr: str) -> bool:
    s = get_settings()
    try:
        return (addr or "").lower() in {a.lower() for a in (s.STABLE_TOKEN_ADDRESSES or [])}
    except Exception:
        return False


def _sqrtPriceX96_to_price_t1_per_t0(sqrtP: int, dec0: int, dec1: int) -> float:
    ratio = Decimal(sqrtP) / Q96
    px = ratio * ratio
    scale = Decimal(10) ** (dec0 - dec1)
    return float(px * scale)  # token1 per token0 (human)


def _prices_from_tick(tick: int, dec0: int, dec1: int) -> Dict[str, float]:
    # IMPORTANT: human token1/token0 uses 10^(dec0-dec1)
    p_t1_t0 = (Decimal("1.0001") ** Decimal(tick)) * (Decimal(10) ** Decimal(dec0 - dec1))
    p_t1_t0_f = float(p_t1_t0)
    p_t0_t1_f = float("inf") if p_t1_t0_f == 0 else float(1.0 / p_t1_t0_f)
    return {"tick": int(tick), "p_t1_t0": p_t1_t0_f, "p_t0_t1": p_t0_t1_f}


def _get_sqrt_ratio_at_tick(tick: int) -> int:
    val = (Decimal("1.0001") ** (Decimal(tick) / 2)) * Q96
    return int(val)


def _get_amounts_for_liquidity(sqrtP: int, sqrtA: int, sqrtB: int, L: int) -> Tuple[int, int]:
    """
    Uniswap v3 math with Q64.96 sqrt prices.
    Returns raw token amounts (uint256-like integers).
    """
    sp = Decimal(sqrtP)
    sa = Decimal(sqrtA)
    sb = Decimal(sqrtB)
    liq = Decimal(L)
    q96 = Q96  # Decimal(2) ** 96

    if sa > sb:
        sa, sb = sb, sa

    if liq <= 0:
        return 0, 0

    if sp <= sa:
        # amount0 = L * (sb - sa) / (sa * sb) * Q96
        amount0 = liq * (sb - sa) * q96 / (sa * sb)
        return int(amount0), 0

    if sp < sb:
        # amount0 = L * (sb - sp) / (sp * sb) * Q96
        amount0 = liq * (sb - sp) * q96 / (sp * sb)
        # amount1 = L * (sp - sa) / Q96
        amount1 = liq * (sp - sa) / q96
        return int(amount0), int(amount1)

    # sp >= sb
    # amount1 = L * (sb - sa) / Q96
    amount1 = liq * (sb - sa) / q96
    return 0, int(amount1)



@dataclass
class VaultStatusService:
    w3: Web3

    def _erc20(self, addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_ERC20)

    def _nfpm(self, addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_NFPM)

    def _v3_pool(self, addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_V3_POOL_MIN)

    def _gauge_generic(self, addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_GAUGE_MIN)

    def _pancake_masterchef(self, addr: str) -> Contract:
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI_PANCAKE_MASTERCHEF_MIN)

    # ----------------- batch eth_call -----------------

    def _rpc_batch_call(self, calls: List[_CallSpec]) -> List[Optional[Any]]:
        """
        Batch JSON-RPC eth_call. Falls back to sequential eth_call if batch unsupported.
        Returns decoded values (single output => value, multi => tuple), None on error per-call.
        """
        if not calls:
            return []

        endpoint = getattr(self.w3.provider, "endpoint_uri", None)
        payload = []
        for i, c in enumerate(calls):
            payload.append(
                {
                    "jsonrpc": "2.0",
                    "id": i + 1,
                    "method": "eth_call",
                    "params": [{"to": Web3.to_checksum_address(c.to), "data": c.data}, "latest"],
                }
            )

        def _decode(spec: _CallSpec, raw_hex_or_bytes: Any) -> Optional[Any]:
            try:
                if raw_hex_or_bytes is None:
                    return None
                if isinstance(raw_hex_or_bytes, (bytes, bytearray, HexBytes)):
                    raw = HexBytes(raw_hex_or_bytes)
                else:
                    raw = HexBytes(raw_hex_or_bytes)
                decoded = self.w3.codec.decode(spec.out_types, raw)  # type: ignore[attr-defined]
                if len(spec.out_types) == 1:
                    return decoded[0]
                return tuple(decoded)
            except Exception:
                return None

        # try batch
        if endpoint:
            try:
                r = requests.post(endpoint, json=payload, timeout=12)
                data = r.json()
                if isinstance(data, list):
                    by_id = {it.get("id"): it for it in data if isinstance(it, dict)}
                    out: List[Optional[Any]] = []
                    for i, spec in enumerate(calls):
                        it = by_id.get(i + 1) or {}
                        if "error" in it:
                            out.append(None)
                            continue
                        out.append(_decode(spec, it.get("result")))
                    return out
            except Exception:
                pass

        # fallback sequential
        out2: List[Optional[Any]] = []
        for spec in calls:
            try:
                raw = self.w3.eth.call({"to": Web3.to_checksum_address(spec.to), "data": spec.data})
                out2.append(_decode(spec, raw))
            except Exception:
                out2.append(None)
        return out2
    
    # ----------------- meta caches -----------------

    def _get_token_meta_cached(self, *, chain: str, token_addr: str, timings: Dict[str, float], debug_timing: bool) -> Tuple[int, str]:
        key = f"{chain}:{token_addr.lower()}"
        hit = _cache_get(_TOKEN_META_CACHE, key, _TOKEN_META_TTL_SEC)
        if hit:
            return int(hit["decimals"]), str(hit["symbol"])

        t = perf_counter()
        erc = self._erc20(token_addr)

        dec = 18
        sym = "TKN"
        try:
            dec = int(erc.functions.decimals().call())
        except Exception:
            dec = 18
        try:
            sym = str(erc.functions.symbol().call())
        except Exception:
            sym = "TKN"

        _cache_set(_TOKEN_META_CACHE, key, {"decimals": int(dec), "symbol": str(sym)})

        if debug_timing:
            timings.setdefault("token_meta_cache_miss_calls", 0.0)
            timings["token_meta_cache_miss_calls"] += (perf_counter() - t) * 1000.0

        return int(dec), str(sym)

    def _get_vault_static_cached(
        self,
        *,
        chain: str,
        vault_address: str,
        vault: ClientVaultAdapter,
        static_in: Dict[str, Any],
        timings: Dict[str, float],
        debug_timing: bool,
        fresh_onchain: bool,
    ) -> Dict[str, Any]:
        key = f"{chain}:{vault_address.lower()}"
        if not fresh_onchain:
            hit = _cache_get(_VAULT_STATIC_CACHE, key, _VAULT_STATIC_TTL_SEC) or {}
        else:
            hit = {}

        out = dict(hit)
        out.update({k: v for k, v in (static_in or {}).items() if v is not None})

        if not out.get("executor"):
            t = perf_counter()
            try:
                out["executor"] = Web3.to_checksum_address(vault.executor())
            except Exception:
                out["executor"] = ZERO_ADDR
            if debug_timing:
                timings["vault_read_executor"] = (perf_counter() - t) * 1000.0

        if not out.get("fee_collector"):
            t = perf_counter()
            try:
                out["fee_collector"] = Web3.to_checksum_address(vault.fee_collector())
            except Exception:
                out["fee_collector"] = ZERO_ADDR
            if debug_timing:
                timings["vault_read_fee_collector"] = (perf_counter() - t) * 1000.0

        _cache_set(_VAULT_STATIC_CACHE, key, {
            "executor": out.get("executor"),
            "fee_collector": out.get("fee_collector"),
        })
        return out

    def _get_erc20_balance_cached(self, *, chain: str, token: str, owner: str, fresh_onchain: bool) -> Optional[int]:
        key = f"{chain}:bal:{token.lower()}:{owner.lower()}"
        if not fresh_onchain:
            hit = _cache_get(_ERC20_BAL_CACHE, key, _ERC20_BAL_TTL_SEC)
            if hit and "bal" in hit:
                try:
                    return int(hit["bal"])
                except Exception:
                    pass
        return None

    def _set_erc20_balance_cached(self, *, chain: str, token: str, owner: str, bal: int) -> None:
        key = f"{chain}:bal:{token.lower()}:{owner.lower()}"
        _cache_set(_ERC20_BAL_CACHE, key, {"bal": int(bal)})

    def _get_nfpm_pos_cached(self, *, chain: str, nfpm: str, token_id: int, fresh_onchain: bool) -> Optional[Dict[str, Any]]:
        key = f"{chain}:nfpm_pos:{nfpm.lower()}:{int(token_id)}"
        if not fresh_onchain:
            return _cache_get(_NFPM_POS_CACHE, key, _NFPM_POS_TTL_SEC)
        return None

    def _set_nfpm_pos_cached(self, *, chain: str, nfpm: str, token_id: int, lower: int, upper: int, liq: int) -> None:
        key = f"{chain}:nfpm_pos:{nfpm.lower()}:{int(token_id)}"
        _cache_set(_NFPM_POS_CACHE, key, {"lower": int(lower), "upper": int(upper), "liq": int(liq)})

    def _get_nfpm_collect_cached(self, *, chain: str, nfpm: str, token_id: int, vault_addr: str, fresh_onchain: bool) -> Optional[Dict[str, Any]]:
        key = f"{chain}:nfpm_collect:{nfpm.lower()}:{int(token_id)}:{vault_addr.lower()}"
        if not fresh_onchain:
            return _cache_get(_NFPM_COLLECT_PREVIEW_CACHE, key, _NFPM_COLLECT_PREVIEW_TTL_SEC)
        return None

    def _set_nfpm_collect_cached(self, *, chain: str, nfpm: str, token_id: int, vault_addr: str, a0: int, a1: int) -> None:
        key = f"{chain}:nfpm_collect:{nfpm.lower()}:{int(token_id)}:{vault_addr.lower()}"
        _cache_set(_NFPM_COLLECT_PREVIEW_CACHE, key, {"a0": int(a0), "a1": int(a1)})

    def _get_nft_owner_cached(self, *, chain: str, nfpm: str, token_id: int, fresh_onchain: bool) -> Optional[str]:
        key = f"{chain}:nft_owner:{nfpm.lower()}:{int(token_id)}"
        if not fresh_onchain:
            hit = _cache_get(_NFT_OWNER_CACHE, key, _NFT_OWNER_TTL_SEC)
            if hit and "owner" in hit:
                return str(hit["owner"])
        return None

    def _set_nft_owner_cached(self, *, chain: str, nfpm: str, token_id: int, owner: str) -> None:
        key = f"{chain}:nft_owner:{nfpm.lower()}:{int(token_id)}"
        _cache_set(_NFT_OWNER_CACHE, key, {"owner": str(owner)})

    def _get_pancake_reward_token_cached(self, *, chain: str, gauge: str, fresh_onchain: bool) -> Optional[str]:
        key = f"{chain}:pancake_reward:{gauge.lower()}"
        if not fresh_onchain:
            hit = _cache_get(_GAUGE_REWARD_TOKEN_CACHE, key, _GAUGE_REWARD_TOKEN_TTL_SEC)
            if hit and "reward" in hit:
                return str(hit["reward"])
        return None

    def _set_pancake_reward_token_cached(self, *, chain: str, gauge: str, reward: str) -> None:
        key = f"{chain}:pancake_reward:{gauge.lower()}"
        _cache_set(_GAUGE_REWARD_TOKEN_CACHE, key, {"reward": str(reward)})

    def _get_v3_pool_meta_cached(self, *, chain: str, pool_addr: str, fresh_onchain: bool) -> Optional[Dict[str, Any]]:
        key = f"{chain}:v3_meta:{pool_addr.lower()}"
        if not fresh_onchain:
            return _cache_get(_V3_POOL_META_CACHE, key, _V3_POOL_META_TTL_SEC)
        return None

    def _set_v3_pool_meta_cached(self, *, chain: str, pool_addr: str, t0: str, t1: str) -> None:
        key = f"{chain}:v3_meta:{pool_addr.lower()}"
        _cache_set(_V3_POOL_META_CACHE, key, {"token0": _to_checksum(t0), "token1": _to_checksum(t1)})

    def _get_v3_pool_slot0_cached(self, *, chain: str, pool_addr: str, fresh_onchain: bool) -> Optional[Dict[str, Any]]:
        key = f"{chain}:v3_slot0:{pool_addr.lower()}"
        if not fresh_onchain:
            return _cache_get(_V3_POOL_SLOT0_CACHE, key, _V3_POOL_SLOT0_TTL_SEC)
        return None

    def _set_v3_pool_slot0_cached(self, *, chain: str, pool_addr: str, sqrtP: int, tick: int) -> None:
        key = f"{chain}:v3_slot0:{pool_addr.lower()}"
        _cache_set(_V3_POOL_SLOT0_CACHE, key, {"sqrtP": int(sqrtP), "tick": int(tick)})

    
    # ----------------- Pancake USD estimate (cached) -----------------

    def _pancake_reward_usd_est_cached(
        self,
        *,
        chain: str,
        swap_pools: Dict[str, Any],
        pending_amount: float,
        reward_token_addr: str,
        timings: Dict[str, float],
        debug_timing: bool,
        fresh_onchain: bool,
    ) -> Optional[float]:
        if pending_amount <= 0:
            return 0.0

        ref = swap_pools.get("CAKE_USDC") or swap_pools.get("cake_usdc")
        pool_addr = None
        if ref is not None:
            pool_addr = getattr(ref, "pool", None) or (ref.get("pool") if isinstance(ref, dict) else None)

        if not pool_addr:
            return None

        pool_addr = Web3.to_checksum_address(pool_addr)

        # pool meta (token0/token1) cached 24h
        meta = self._get_v3_pool_meta_cached(chain=chain, pool_addr=pool_addr, fresh_onchain=fresh_onchain)
        t0 = meta.get("token0") if meta else None
        t1 = meta.get("token1") if meta else None

        if not t0 or not t1:
            pool = self._v3_pool(pool_addr)
            calls = [
                _CallSpec(to=pool_addr, data=_enc(pool, "token0"), out_types=["address"]),
                _CallSpec(to=pool_addr, data=_enc(pool, "token1"), out_types=["address"]),
            ]
            r0, r1 = self._rpc_batch_call(calls)
            t0 = _to_checksum(r0) if r0 is not None else ZERO_ADDR
            t1 = _to_checksum(r1) if r1 is not None else ZERO_ADDR
            self._set_v3_pool_meta_cached(chain=chain, pool_addr=pool_addr, t0=t0, t1=t1)

        # slot0 cached short (15s)
        slot = self._get_v3_pool_slot0_cached(chain=chain, pool_addr=pool_addr, fresh_onchain=fresh_onchain)
        sqrtP = int(slot["sqrtP"]) if slot and "sqrtP" in slot else None

        if sqrtP is None:
            pool = self._v3_pool(pool_addr)
            t_slot = perf_counter()
            res = self._rpc_batch_call([
                _CallSpec(
                    to=pool_addr,
                    data=_enc(pool, "slot0"),
                    out_types=["uint160", "int24", "uint16", "uint16", "uint16", "uint32", "bool"],
                )
            ])
            if debug_timing:
                timings.setdefault("gauge_reward_usd_est_slot0_call", 0.0)
                timings["gauge_reward_usd_est_slot0_call"] += (perf_counter() - t_slot) * 1000.0

            if res and res[0] is not None:
                slot0 = res[0]
                if isinstance(slot0, tuple) and len(slot0) >= 2:
                    sqrtP = int(slot0[0])
                    tick = int(slot0[1])
                    self._set_v3_pool_slot0_cached(chain=chain, pool_addr=pool_addr, sqrtP=sqrtP, tick=tick)

        if sqrtP is None:
            return None

        # token metas (cached globally)
        dec0, sym0 = self._get_token_meta_cached(chain=chain, token_addr=t0, timings={}, debug_timing=False)
        dec1, sym1 = self._get_token_meta_cached(chain=chain, token_addr=t1, timings={}, debug_timing=False)

        p_t1_t0 = _sqrtPriceX96_to_price_t1_per_t0(int(sqrtP), int(dec0), int(dec1))

        reward = Web3.to_checksum_address(reward_token_addr)
        t0c = Web3.to_checksum_address(t0)
        t1c = Web3.to_checksum_address(t1)

        price_reward_usd: Optional[float] = None
        if reward == t0c and (_is_usd_symbol(sym1) or _is_stable_addr(t1c)):
            price_reward_usd = float(p_t1_t0)
        elif reward == t1c and (_is_usd_symbol(sym0) or _is_stable_addr(t0c)):
            price_reward_usd = 0.0 if p_t1_t0 == 0 else float(1.0 / p_t1_t0)

        if price_reward_usd is None:
            return None

        return float(pending_amount) * float(price_reward_usd)


    # ----------------- main -----------------

    def compute(
        self,
        vault_address: str,
        dex: str = "",
        swap_pools: Optional[Dict[str, Any]] = None,
        static: Optional[Dict[str, Any]] = None,
        debug_timing: bool = False,
        fresh_onchain: bool = False,
    ) -> Dict[str, Any]:
        swap_pools = swap_pools or {}
        timings: Dict[str, float] = {}

        def mark(name: str, t_start: float) -> None:
            if debug_timing:
                timings[name] = (perf_counter() - t_start) * 1000.0

        t_all = perf_counter()

        st = static or {}
        chain = (st.get("chain") or "").strip().lower() or "unknown"
        dex = (st.get("dex") or dex or "").strip().lower()

        vault_address = Web3.to_checksum_address(vault_address)

        # ---------- vault reads ----------
        t = perf_counter()
        vault = ClientVaultAdapter(w3=self.w3, address=vault_address)

        owner = st.get("owner") or ZERO_ADDR
        try:
            owner = Web3.to_checksum_address(owner)
        except Exception:
            owner = owner or ZERO_ADDR

        adapter_addr = st.get("adapter") or ZERO_ADDR
        pool_addr = st.get("pool") or ZERO_ADDR
        nfpm_addr = st.get("nfpm") or ZERO_ADDR
        gauge = st.get("gauge") or ZERO_ADDR

        strategy_id = int(st.get("strategy_id") or 0)
        dex_router = st.get("dex_router")

        filled = self._get_vault_static_cached(
            chain=chain,
            vault_address=vault_address,
            vault=vault,
            static_in=st,
            timings=timings,
            debug_timing=debug_timing,
            fresh_onchain=fresh_onchain,
        )
        executor = filled.get("executor") or ZERO_ADDR
        fee_collector = filled.get("fee_collector") or ZERO_ADDR

        position_token_id = 0
        last_rebalance_ts = 0
        try:
            position_token_id = int(vault.position_token_id())
        except Exception:
            position_token_id = 0
        try:
            last_rebalance_ts = int(vault.last_rebalance_ts())
        except Exception:
            last_rebalance_ts = 0

        mark("vault_reads", t)

        # ---------- adapter_reads (pool slot0 + tokens if missing) ----------
        t = perf_counter()

        pool_addr = Web3.to_checksum_address(pool_addr)
        nfpm_addr = Web3.to_checksum_address(nfpm_addr)
        try:
            gauge = Web3.to_checksum_address(gauge)
        except Exception:
            gauge = ZERO_ADDR
        adapter_addr = Web3.to_checksum_address(adapter_addr)

        poolc = self._v3_pool(pool_addr)
        slot0 = poolc.functions.slot0().call()
        sqrt_price_x96 = int(slot0[0])
        tick = int(slot0[1])

        tick_spacing = 0
        try:
            tick_spacing = int(poolc.functions.tickSpacing().call())
        except Exception:
            tick_spacing = 0

        token0_addr = st.get("token0")
        token1_addr = st.get("token1")

        if not token0_addr or not token1_addr:
            try:
                token0_addr = Web3.to_checksum_address(poolc.functions.token0().call())
            except Exception:
                token0_addr = ZERO_ADDR
            try:
                token1_addr = Web3.to_checksum_address(poolc.functions.token1().call())
            except Exception:
                token1_addr = ZERO_ADDR
        else:
            token0_addr = Web3.to_checksum_address(token0_addr)
            token1_addr = Web3.to_checksum_address(token1_addr)

        mark("adapter_reads", t)

        # ---------- token meta (cached) ----------
        t = perf_counter()
        dec0, sym0 = self._get_token_meta_cached(chain=chain, token_addr=token0_addr, timings=timings, debug_timing=debug_timing)
        dec1, sym1 = self._get_token_meta_cached(chain=chain, token_addr=token1_addr, timings=timings, debug_timing=debug_timing)
        mark("token_meta", t)

        # ---------- nfpm reads (batch + caches) ----------
        t = perf_counter()
        lower_tick = upper_tick = 0
        liquidity = 0
        fees0_raw = 0
        fees1_raw = 0

        has_gauge = bool(gauge and Web3.to_checksum_address(gauge) != ZERO_ADDR)
        staked = False
        position_location = "none"

        if position_token_id:
            nfpm = self._nfpm(nfpm_addr)

            pos_hit = self._get_nfpm_pos_cached(chain=chain, nfpm=nfpm_addr, token_id=position_token_id, fresh_onchain=fresh_onchain)
            collect_hit = self._get_nfpm_collect_cached(chain=chain, nfpm=nfpm_addr, token_id=position_token_id, vault_addr=vault_address, fresh_onchain=fresh_onchain)
            owner_hit = self._get_nft_owner_cached(chain=chain, nfpm=nfpm_addr, token_id=position_token_id, fresh_onchain=fresh_onchain)

            need_pos = not (pos_hit and "lower" in pos_hit and "upper" in pos_hit and "liq" in pos_hit)
            need_collect = not (collect_hit and "a0" in collect_hit and "a1" in collect_hit)
            need_owner = not (owner_hit and Web3.is_address(owner_hit))

            calls: List[_CallSpec] = []
            idx_pos = idx_collect = idx_owner = -1

            if need_pos:
                idx_pos = len(calls)
                calls.append(_CallSpec(
                    to=nfpm_addr,
                    data=_enc(nfpm, "positions", [int(position_token_id)]),
                    out_types=["uint96","address","address","address","uint24","int24","int24","uint128","uint256","uint256","uint128","uint128"],
                ))
            if need_collect:
                idx_collect = len(calls)
                calls.append(_CallSpec(
                    to=nfpm_addr,
                    data=_enc(nfpm, "collect", [(int(position_token_id), Web3.to_checksum_address(vault_address), int(U128_MAX), int(U128_MAX))]),
                    out_types=["uint256", "uint256"],
                ))
            if need_owner:
                idx_owner = len(calls)
                calls.append(_CallSpec(
                    to=nfpm_addr,
                    data=_enc(nfpm, "ownerOf", [int(position_token_id)]),
                    out_types=["address"],
                ))

            if calls:
                res = self._rpc_batch_call(calls)

                if idx_pos >= 0 and idx_pos < len(res) and res[idx_pos] is not None:
                    p = res[idx_pos]
                    # outputs: ... tickLower(5), tickUpper(6), liquidity(7)
                    if isinstance(p, tuple) and len(p) >= 8:
                        lower_tick = int(p[5])
                        upper_tick = int(p[6])
                        liquidity = int(p[7])
                        self._set_nfpm_pos_cached(chain=chain, nfpm=nfpm_addr, token_id=position_token_id, lower=lower_tick, upper=upper_tick, liq=liquidity)

                if idx_collect >= 0 and idx_collect < len(res) and res[idx_collect] is not None:
                    c = res[idx_collect]
                    if isinstance(c, tuple) and len(c) >= 2:
                        fees0_raw = int(c[0])
                        fees1_raw = int(c[1])
                        self._set_nfpm_collect_cached(chain=chain, nfpm=nfpm_addr, token_id=position_token_id, vault_addr=vault_address, a0=fees0_raw, a1=fees1_raw)

                if idx_owner >= 0 and idx_owner < len(res) and res[idx_owner] is not None:
                    owner_of = _to_checksum(res[idx_owner])
                    self._set_nft_owner_cached(chain=chain, nfpm=nfpm_addr, token_id=position_token_id, owner=owner_of)
                    owner_hit = owner_of

            # fill from caches if still missing
            if pos_hit and (lower_tick, upper_tick, liquidity) == (0, 0, 0):
                try:
                    lower_tick = int(pos_hit.get("lower", 0))
                    upper_tick = int(pos_hit.get("upper", 0))
                    liquidity = int(pos_hit.get("liq", 0))
                except Exception:
                    pass
            if collect_hit and (fees0_raw, fees1_raw) == (0, 0):
                try:
                    fees0_raw = int(collect_hit.get("a0", 0))
                    fees1_raw = int(collect_hit.get("a1", 0))
                except Exception:
                    pass

            # stake detection (ownerOf cached)
            try:
                owner_of = owner_hit or nfpm.functions.ownerOf(int(position_token_id)).call()
                owner_of = Web3.to_checksum_address(owner_of)
                if has_gauge and owner_of == Web3.to_checksum_address(gauge):
                    staked = True
                    position_location = "gauge"
                else:
                    staked = False
                    position_location = "pool"
            except Exception:
                position_location = "pool"
        else:
            position_location = "none"

        mark("nfpm_reads", t)

        # ---------- idle balances (batch + cache) ----------
        t = perf_counter()
        e0 = self._erc20(token0_addr)
        e1 = self._erc20(token1_addr)

        bal0_idle_raw = self._get_erc20_balance_cached(chain=chain, token=token0_addr, owner=vault_address, fresh_onchain=fresh_onchain)
        bal1_idle_raw = self._get_erc20_balance_cached(chain=chain, token=token1_addr, owner=vault_address, fresh_onchain=fresh_onchain)

        calls_bal: List[_CallSpec] = []
        idx0 = idx1 = -1

        if bal0_idle_raw is None:
            idx0 = len(calls_bal)
            calls_bal.append(_CallSpec(
                to=token0_addr,
                data=_enc(e0, "balanceOf", [Web3.to_checksum_address(vault_address)]),
                out_types=["uint256"],
            ))
        if bal1_idle_raw is None:
            idx1 = len(calls_bal)
            calls_bal.append(_CallSpec(
                to=token1_addr,
                data=_enc(e1, "balanceOf", [Web3.to_checksum_address(vault_address)]),
                out_types=["uint256"],
            ))

        if calls_bal:
            resb = self._rpc_batch_call(calls_bal)
            if idx0 >= 0 and idx0 < len(resb) and resb[idx0] is not None:
                bal0_idle_raw = int(resb[idx0])
                self._set_erc20_balance_cached(chain=chain, token=token0_addr, owner=vault_address, bal=bal0_idle_raw)
            if idx1 >= 0 and idx1 < len(resb) and resb[idx1] is not None:
                bal1_idle_raw = int(resb[idx1])
                self._set_erc20_balance_cached(chain=chain, token=token1_addr, owner=vault_address, bal=bal1_idle_raw)

        if bal0_idle_raw is None:
            bal0_idle_raw = 0
        if bal1_idle_raw is None:
            bal1_idle_raw = 0

        vault_idle0 = float(Decimal(int(bal0_idle_raw)) / (Decimal(10) ** dec0))
        vault_idle1 = float(Decimal(int(bal1_idle_raw)) / (Decimal(10) ** dec1))
        mark("idle_balances", t)

        # ---------- in-position math ----------
        t = perf_counter()
        inpos0 = 0.0
        inpos1 = 0.0
        if position_token_id and liquidity and lower_tick != upper_tick:
            sqrtA = _get_sqrt_ratio_at_tick(lower_tick)
            sqrtB = _get_sqrt_ratio_at_tick(upper_tick)
            amt0_raw, amt1_raw = _get_amounts_for_liquidity(sqrt_price_x96, sqrtA, sqrtB, liquidity)
            inpos0 = float(Decimal(amt0_raw) / (Decimal(10) ** dec0))
            inpos1 = float(Decimal(amt1_raw) / (Decimal(10) ** dec1))
        totals0 = vault_idle0 + inpos0
        totals1 = vault_idle1 + inpos1
        mark("in_position_math", t)

        # ---------- prices ----------
        t = perf_counter()
        current_block = _prices_from_tick(tick, dec0, dec1)
        lower_block = _prices_from_tick(lower_tick, dec0, dec1) if position_token_id else current_block
        upper_block = _prices_from_tick(upper_tick, dec0, dec1) if position_token_id else current_block
        mark("prices_calc", t)

        # ---------- range flags ----------
        t = perf_counter()
        out_of_range = False
        range_side = "inside"
        if position_token_id:
            out_of_range = tick < lower_tick or tick >= upper_tick
            if out_of_range:
                range_side = "below" if tick < lower_tick else "above"
        mark("range_flags", t)

        # ---------- fees ----------
        t = perf_counter()
        fees0_h = float(Decimal(int(fees0_raw)) / (Decimal(10) ** dec0))
        fees1_h = float(Decimal(int(fees1_raw)) / (Decimal(10) ** dec1))

        fees_usd: Optional[float] = None
        try:
            p_t1_t0 = float(current_block["p_t1_t0"])
            if _is_usd_symbol(sym1) or _is_stable_addr(token1_addr):
                fees_usd = float(fees0_h * p_t1_t0 + fees1_h)
            elif _is_usd_symbol(sym0) or _is_stable_addr(token0_addr):
                p_t0_t1 = float(current_block["p_t0_t1"])
                fees_usd = float(fees1_h * p_t0_t1 + fees0_h)
        except Exception:
            fees_usd = None
        mark("fees_calc", t)

        # ---------- gauge rewards (batch + caches) ----------
        t = perf_counter()
        gauge_rewards = {
            "reward_token": ZERO_ADDR,
            "reward_symbol": "N/A",
            "pending_raw": 0,
            "pending_amount": 0.0,
            "pending_usd_est": None,
        }
        gauge_reward_balances = {
            "token": ZERO_ADDR,
            "symbol": "N/A",
            "decimals": 18,
            "in_vault_raw": 0,
            "in_vault": 0.0,
        }

        if has_gauge and position_token_id:
            try:
                pending_raw = 0
                reward_token_addr = ZERO_ADDR
                reward_symbol = "REWARD"
                reward_dec = 18
                pending_h = 0.0
                pending_usd_est: Optional[float] = None

                if (dex or "").strip().lower() == "pancake_v3":
                    mc = self._pancake_masterchef(gauge)

                    # reward token cached (CAKE())
                    cached_reward = self._get_pancake_reward_token_cached(chain=chain, gauge=gauge, fresh_onchain=fresh_onchain)

                    # batch: pendingCake + (optional) CAKE()
                    t2 = perf_counter()
                    calls = [
                        _CallSpec(to=gauge, data=_enc(mc, "pendingCake", [int(position_token_id)]), out_types=["uint256"]),
                    ]
                    need_cake = not (cached_reward and Web3.is_address(cached_reward))
                    if need_cake:
                        calls.append(_CallSpec(to=gauge, data=_enc(mc, "CAKE"), out_types=["address"]))
                    
                    res = self._rpc_batch_call(calls)
                    if res and res[0] is not None:
                        pending_raw = int(res[0])
                    if need_cake:
                        reward_token_addr = _to_checksum(res[1]) if len(res) > 1 and res[1] is not None else ZERO_ADDR
                        if Web3.is_address(reward_token_addr):
                            self._set_pancake_reward_token_cached(chain=chain, gauge=gauge, reward=reward_token_addr)
                    else:
                        reward_token_addr = _to_checksum(cached_reward)

                    if debug_timing:
                        timings["gauge_pancake_pending_and_token"] = (perf_counter() - t2) * 1000.0

                    # reward meta cached (already good)
                    t2 = perf_counter()
                    reward_dec, reward_symbol = self._get_token_meta_cached(
                        chain=chain,
                        token_addr=reward_token_addr,
                        timings=timings,
                        debug_timing=debug_timing,
                    )
                    if debug_timing:
                        timings["gauge_reward_meta"] = (perf_counter() - t2) * 1000.0

                    pending_h = float(pending_raw) / (10 ** int(reward_dec))

                    if _is_usd_symbol(reward_symbol) or _is_stable_addr(reward_token_addr):
                        pending_usd_est = float(pending_h)
                    else:
                        t2 = perf_counter()
                        pending_usd_est = self._pancake_reward_usd_est_cached(
                            chain=chain,
                            swap_pools=swap_pools,
                            pending_amount=pending_h,
                            reward_token_addr=reward_token_addr,
                            timings=timings,
                            debug_timing=debug_timing,
                            fresh_onchain=fresh_onchain,
                        )
                        if debug_timing:
                            timings["gauge_reward_usd_est"] = (perf_counter() - t2) * 1000.0

                else:
                    g = self._gauge_generic(gauge)

                    # batch: rewardToken + earned
                    t2 = perf_counter()
                    calls = [
                        _CallSpec(to=gauge, data=_enc(g, "rewardToken"), out_types=["address"]),
                        _CallSpec(to=gauge, data=_enc(g, "earned", [Web3.to_checksum_address(adapter_addr), int(position_token_id)]), out_types=["uint256"]),
                    ]
                    res = self._rpc_batch_call(calls)

                    reward_token_addr = _to_checksum(res[0]) if res and res[0] is not None else ZERO_ADDR
                    pending_raw = int(res[1]) if len(res) > 1 and res[1] is not None else 0

                    if debug_timing:
                        timings["gauge_generic_pending_and_token"] = (perf_counter() - t2) * 1000.0

                    t2 = perf_counter()
                    reward_dec, reward_symbol = self._get_token_meta_cached(
                        chain=chain,
                        token_addr=reward_token_addr,
                        timings=timings,
                        debug_timing=debug_timing,
                    )
                    if debug_timing:
                        timings["gauge_reward_meta"] = (perf_counter() - t2) * 1000.0

                    pending_h = float(pending_raw) / (10 ** int(reward_dec))
                    if _is_usd_symbol(reward_symbol) or _is_stable_addr(reward_token_addr):
                        pending_usd_est = float(pending_h)

                gauge_rewards = {
                    "reward_token": Web3.to_checksum_address(reward_token_addr),
                    "reward_symbol": reward_symbol,
                    "pending_raw": int(pending_raw),
                    "pending_amount": float(pending_h),
                    "pending_usd_est": float(pending_usd_est) if pending_usd_est is not None else None,
                }

                # reward balanceOf (cache short + batch)
                try:
                    t2 = perf_counter()
                    in_vault_raw = self._get_erc20_balance_cached(chain=chain, token=reward_token_addr, owner=vault_address, fresh_onchain=fresh_onchain)

                    if in_vault_raw is None:
                        erc_r = self._erc20(reward_token_addr)
                        resb = self._rpc_batch_call([
                            _CallSpec(
                                to=reward_token_addr,
                                data=_enc(erc_r, "balanceOf", [Web3.to_checksum_address(vault_address)]),
                                out_types=["uint256"],
                            )
                        ])
                        in_vault_raw = int(resb[0]) if resb and resb[0] is not None else 0
                        self._set_erc20_balance_cached(chain=chain, token=reward_token_addr, owner=vault_address, bal=in_vault_raw)

                    in_vault = float(int(in_vault_raw)) / (10 ** int(reward_dec))
                    if debug_timing:
                        timings["gauge_reward_balanceOf"] = (perf_counter() - t2) * 1000.0

                    gauge_reward_balances = {
                        "token": Web3.to_checksum_address(reward_token_addr),
                        "symbol": reward_symbol,
                        "decimals": int(reward_dec),
                        "in_vault_raw": int(in_vault_raw),
                        "in_vault": float(in_vault),
                    }
                except Exception:
                    pass

            except Exception:
                pass

        mark("gauge_block", t)

        # ---------- build output ----------
        t = perf_counter()
        out = VaultStatusOut(
            vault=Web3.to_checksum_address(vault_address),

            owner=owner,
            executor=Web3.to_checksum_address(executor) if Web3.is_address(executor) else executor,
            adapter=Web3.to_checksum_address(adapter_addr),

            dex_router=Web3.to_checksum_address(dex_router) if (dex_router and Web3.is_address(dex_router)) else (dex_router or ZERO_ADDR),
            fee_collector=Web3.to_checksum_address(fee_collector) if Web3.is_address(fee_collector) else fee_collector,

            strategy_id=int(strategy_id),

            pool=Web3.to_checksum_address(pool_addr),
            nfpm=Web3.to_checksum_address(nfpm_addr),
            gauge=Web3.to_checksum_address(gauge) if has_gauge else ZERO_ADDR,

            token0=Erc20Meta(address=Web3.to_checksum_address(token0_addr), symbol=str(sym0), decimals=int(dec0)),
            token1=Erc20Meta(address=Web3.to_checksum_address(token1_addr), symbol=str(sym1), decimals=int(dec1)),

            position_token_id=int(position_token_id),
            liquidity=int(liquidity),
            lower_tick=int(lower_tick),
            upper_tick=int(upper_tick),
            tick_spacing=int(tick_spacing),

            tick=int(tick),
            sqrt_price_x96=int(sqrt_price_x96),
            prices=PricesOut(
                current=PriceBlock(**current_block),
                lower=PriceBlock(**lower_block),
                upper=PriceBlock(**upper_block),
            ),

            out_of_range=bool(out_of_range),
            range_side=str(range_side),

            holdings=HoldingsOut(
                vault_idle=HoldingsBlock(token0=float(vault_idle0), token1=float(vault_idle1)),
                in_position=HoldingsBlock(token0=float(inpos0), token1=float(inpos1)),
                totals=HoldingsBlock(token0=float(totals0), token1=float(totals1)),
                symbols={"token0": str(sym0), "token1": str(sym1)},
                addresses={"token0": Web3.to_checksum_address(token0_addr), "token1": Web3.to_checksum_address(token1_addr)},
            ),

            fees_uncollected=FeesUncollectedOut(
                token0=float(fees0_h),
                token1=float(fees1_h),
                usd=(float(fees_usd) if fees_usd is not None else None),
            ),

            last_rebalance_ts=int(last_rebalance_ts),

            has_gauge=bool(has_gauge),
            staked=bool(staked),
            position_location=str(position_location),

            gauge_rewards=GaugeRewardsOut(**gauge_rewards),
            gauge_reward_balances=GaugeRewardBalancesOut(**gauge_reward_balances),
        )
        mark("build_output", t)

        d = out.model_dump()
        if debug_timing:
            timings["total_compute"] = (perf_counter() - t_all) * 1000.0
            d["_timings_ms"] = timings
        return d