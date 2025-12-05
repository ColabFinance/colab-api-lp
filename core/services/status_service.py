"""
Status computation service for vaults.

This module centralizes all read-side logic used to build the "status" panel
for a vault, including:

- On-chain price reads (slot0, TWAP flags, gauge rewards)
- Inventory breakdown (idle vs in-position)
- Uncollected fees preview (callStatic collect)
- Cumulative, already collected fees (from DB state)
- USD valuation rules using stablecoins as anchors
- Cooldown / range / location flags

Historically this logic lived inside `chain_reader.compute_status`. It is now
moved here so that `chain_reader` can act as a thin facade while the core
status logic is reusable and testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Any, Dict

from web3 import Web3

from config import get_settings
from adapters.external.database.state_repo import load_state, save_state
from adapters.external.database import vault_repo
from ..domain.models import (
    PricesBlock,
    PricesPanel,
    RewardsCollectedCum,
    UsdPanelModel,
    HoldingsSide,
    HoldingsMeta,
    HoldingsBlock,
    FeesUncollected,
    StatusCore,
    FeesCollectedCum,
)

# High precision for Uniswap-like math
getcontext().prec = 80
Q96 = Decimal(2) ** 96

# Symbols treated as USD-like for valuation
USD_SYMBOLS = {"USDC", "USDbC", "USDCE", "USDT", "DAI", "USDD", "USDP", "BUSD"}


@dataclass
class UsdPanel:
    """
    Simple helper dataclass to represent a USD panel snapshot.

    This is kept mostly for conceptual clarity; the API exposed to the rest
    of the codebase uses the Pydantic `UsdPanelModel`.
    """

    usd_value: float
    delta_usd: float
    baseline_usd: float


def _pct_from_dtick(d: int) -> float:
    """
    Convert a tick distance into a percentage distance in price terms.

    Args:
        d: Difference in ticks between the current tick and a boundary.

    Returns:
        The absolute percentage distance between prices implied by the ticks.
    """
    factor = pow(1.0001, abs(d))
    return (factor - 1.0) * 100.0


def sqrtPriceX96_to_price_t1_per_t0(sqrtP: int, dec0: int, dec1: int) -> float:
    """
    Convert Uniswap v3 style sqrtPriceX96 into a token1-per-token0 price.

    Example: if token0 = WETH and token1 = USDC, this returns "USDC per WETH".

    Args:
        sqrtP: Q64.96 square-root price (slot0[0]).
        dec0: Number of decimals for token0.
        dec1: Number of decimals for token1.

    Returns:
        The price expressed as token1 per token0.
    """
    ratio = Decimal(sqrtP) / Q96
    px = ratio * ratio
    scale = Decimal(10) ** (dec0 - dec1)
    return float(px * scale)


def prices_from_tick(tick: int, dec0: int, dec1: int) -> Dict[str, float]:
    """
    Build a small price view (token1/token0 and token0/token1) from a tick.

    Args:
        tick: The Uniswap v3 style tick.
        dec0: Decimals of token0.
        dec1: Decimals of token1.

    Returns:
        A dictionary with:
            - tick
            - p_t1_t0: price (token1 per token0)
            - p_t0_t1: price (token0 per token1)
    """
    p_t1_t0 = pow(1.0001, tick) * pow(10.0, dec0 - dec1)
    p_t0_t1 = float("inf") if p_t1_t0 == 0 else (1.0 / p_t1_t0)
    return {"tick": tick, "p_t1_t0": p_t1_t0, "p_t0_t1": p_t0_t1}


def price_to_tick(p_t1_t0: float, dec0: int, dec1: int) -> int:
    """
    Convert a token1-per-token0 price into the nearest Uniswap v3 tick.

    Args:
        p_t1_t0: Price (token1 per token0).
        dec0: Decimals of token0.
        dec1: Decimals of token1.

    Returns:
        The nearest integer tick corresponding to the given price.

    Raises:
        ValueError: If price is not strictly positive.
    """
    if p_t1_t0 <= 0:
        raise ValueError("price must be > 0")

    ratio = p_t1_t0 / (10 ** (dec0 - dec1))
    tick_float = math.log(ratio, 1.0001)
    return int(round(tick_float))


def _is_usd_symbol(sym: str) -> bool:
    """
    Check whether a given ERC20 symbol is treated as USD-like.

    Args:
        sym: ERC20 symbol string.

    Returns:
        True if the symbol is considered USD/stablecoin-like.
    """
    try:
        return sym.upper() in USD_SYMBOLS
    except Exception:
        return False


def _is_stable_addr(addr: str) -> bool:
    """
    Check whether a given token address is configured as a stablecoin.

    The configuration is read from application settings via
    `STABLE_TOKEN_ADDRESSES`.

    Args:
        addr: Token address to check.

    Returns:
        True if the address is among the configured stablecoins, False otherwise.
    """
    s = get_settings()
    try:
        return addr.lower() in {a.lower() for a in (s.STABLE_TOKEN_ADDRESSES or [])}
    except Exception:
        return False


def _value_usd(
    amt0_h: float,
    amt1_h: float,
    p_t1_t0: float,
    p_t0_t1: float,
    sym0: str,
    sym1: str,
    t0_addr: str,
    t1_addr: str,
) -> float:
    """
    Convert a (token0, token1) inventory into a USD-like valuation.

    Rules:
      - If token1 is USD-like: USD = token0 * (token1/token0) + token1
      - If token0 is USD-like: USD = token1 * (token0/token1) + token0
      - Else: fallback treating token1 as the quote asset.

    Args:
        amt0_h: Human-readable amount of token0.
        amt1_h: Human-readable amount of token1.
        p_t1_t0: Price token1 per token0.
        p_t0_t1: Price token0 per token1.
        sym0: Symbol of token0.
        sym1: Symbol of token1.
        t0_addr: Address of token0.
        t1_addr: Address of token1.

    Returns:
        A float representing the USD-like value.
    """
    token1_is_usd = _is_usd_symbol(sym1) or _is_stable_addr(t1_addr)
    token0_is_usd = _is_usd_symbol(sym0) or _is_stable_addr(t0_addr)

    if token1_is_usd:
        return amt0_h * p_t1_t0 + amt1_h
    if token0_is_usd:
        return amt1_h * p_t0_t1 + amt0_h

    # Fallback: treat token1 as quote asset
    return amt0_h * p_t1_t0 + amt1_h


def _pancake_reward_usd_est(
    adapter: Any,
    dex: str,
    alias: str,
    pending_amount: float,
    reward_token_addr: str,
) -> float | None:
    """
    Estimate the USD value of CAKE rewards using a CAKE/USDC reference pool.

    The pool is read from the vault's `swap_pools` configuration, typically
    under the key "CAKE_USDC". If not found, the function attempts to find a
    Pancake pool entry with a valid `pool` address.

    Args:
        adapter: DEX adapter providing Web3 and ABI helpers.
        dex: DEX identifier (e.g., "pancake").
        alias: Vault alias.
        pending_amount: Human-readable pending reward amount.
        reward_token_addr: Address of the reward token (CAKE).

    Returns:
        Estimated USD value of the rewards, or None if it cannot be computed.
    """
    try:
        v = vault_repo.get_vault(dex, alias)
    except Exception:
        v = None
    if not v:
        return None

    sp = (v.get("swap_pools") or {}) if isinstance(v, dict) else {}
    ref = sp.get("CAKE_USDC") or sp.get("cake_usdc")

    # Fallback: try to find any Pancake pool that looks like CAKE/USDC
    if not ref:
        for _k, r in sp.items():
            try:
                if r.get("dex") == "pancake" and Web3.is_address(r.get("pool")):
                    ref = r
                    break
            except Exception:
                continue

    if not ref or ref.get("dex") != "pancake":
        return None

    pool_addr = ref.get("pool")
    if not pool_addr or not Web3.is_address(pool_addr):
        return None

    w3 = adapter.w3
    try:
        pool = w3.eth.contract(
            address=Web3.to_checksum_address(pool_addr),
            abi=adapter.pool_abi(),
        )
        t0 = pool.functions.token0().call()
        t1 = pool.functions.token1().call()

        erc0 = adapter.erc20(t0)
        erc1 = adapter.erc20(t1)

        dec0 = int(erc0.functions.decimals().call())
        dec1 = int(erc1.functions.decimals().call())

        try:
            sym0 = erc0.functions.symbol().call()
        except Exception:
            sym0 = "T0"
        try:
            sym1 = erc1.functions.symbol().call()
        except Exception:
            sym1 = "T1"

        slot0 = pool.functions.slot0().call()
        sqrtP = int(slot0[0])
        p_t1_t0 = sqrtPriceX96_to_price_t1_per_t0(sqrtP, dec0, dec1)

        reward = Web3.to_checksum_address(reward_token_addr)

        price_cake_usd: float | None = None

        # Typical case: token0 = CAKE, token1 = USDC
        if reward == Web3.to_checksum_address(t0) and _is_usd_symbol(sym1):
            price_cake_usd = float(p_t1_t0)

        # Inverted: token1 = CAKE, token0 = USDC
        elif reward == Web3.to_checksum_address(t1) and _is_usd_symbol(sym0):
            if p_t1_t0 > 0:
                price_cake_usd = float(1.0 / p_t1_t0)

        if price_cake_usd is None:
            return None

        return float(pending_amount) * float(price_cake_usd)

    except Exception:
        return None


def compute_status(adapter: Any, dex: str, alias: str) -> StatusCore:
    """
    Build a full `StatusCore` model for a given vault.

    The adapter is expected to expose the same methods used by the previous
    implementation:

      - pool_meta()
      - slot0()
      - vault_state()
      - gauge_contract()
      - erc20(address)
      - call_static_collect(token_id, recipient)
      - amounts_in_position_now(lower, upper, liquidity)
      - vault.address
      - w3 (Web3 provider)

    Args:
        adapter: DEX adapter bound to the vault contract.
        dex: DEX identifier ("uniswap", "aerodrome", "pancake", etc.).
        alias: Logical alias of the vault.

    Returns:
        A fully populated `StatusCore` instance representing prices, holdings,
        fees, rewards, USD panel, range state and gauge information.
    """
    # ---- Load persisted state (short state, cumulative fields, baseline, etc.)
    st = load_state(dex, alias)

    # ---- Pool & token metadata
    meta = adapter.pool_meta()
    dec0, dec1 = int(meta["dec0"]), int(meta["dec1"])
    sym0, sym1 = meta["sym0"], meta["sym1"]
    t0_addr, t1_addr = meta["token0"], meta["token1"]
    tick_spacing = int(meta["spacing"])

    # ---- Pool slot0 and vault position state
    sqrtP, tick = adapter.slot0()
    vstate = adapter.vault_state()
    lower, upper, liq = int(vstate["lower"]), int(vstate["upper"]), int(vstate["liq"])

    twap_ok = bool(vstate.get("twapOk", True))
    last_rebalance = int(vstate.get("lastRebalance", 0))
    min_cd = int(vstate.get("min_cd", 0))

    # --- Gauge & staking flags
    gauge_addr = vstate.get("gauge")
    has_gauge = bool(gauge_addr)
    is_staked = bool(vstate.get("staked", False))
    token_id = int(vstate.get("tokenId", 0) or 0)

    # ---- Gauge pending rewards (Aero, Cake, etc.)
    gauge_rewards_block: Dict[str, Any] | None = None
    if has_gauge and token_id != 0:
        try:
            if dex == "pancake":
                # MasterChefV3 (Pancake) rewards in CAKE
                mc = adapter.gauge_contract()
                if mc is not None:
                    pending_raw = int(mc.functions.pendingCake(int(token_id)).call())
                    reward_token_addr = mc.functions.CAKE().call()
                    erc = adapter.erc20(reward_token_addr)

                    r_sym = erc.functions.symbol().call()
                    r_dec = int(erc.functions.decimals().call())
                    pending_h = float(pending_raw) / (10 ** r_dec)

                    usd_est = _pancake_reward_usd_est(
                        adapter=adapter,
                        dex=dex,
                        alias=alias,
                        pending_amount=pending_h,
                        reward_token_addr=reward_token_addr,
                    )

                    gauge_rewards_block = {
                        "reward_token": reward_token_addr,
                        "reward_symbol": r_sym,
                        "pending_raw": pending_raw,
                        "pending_amount": pending_h,
                        "pending_usd_est": float(usd_est) if usd_est is not None else None,
                    }
            else:
                gauge = adapter.gauge_contract()

                adapter_onchain_addr = adapter.adapter_address()

                pending_raw = gauge.functions.earned(
                    Web3.to_checksum_address(adapter_onchain_addr),
                    token_id,
                ).call()

                reward_token_addr = gauge.functions.rewardToken().call()

                erc20 = adapter.erc20(reward_token_addr)

                reward_symbol = erc20.functions.symbol().call()
                reward_dec = int(erc20.functions.decimals().call())

                pending_human = float(pending_raw) / (10 ** reward_dec)

                # attempt of usd_est: if reward is stable, treat 1:1
                usd_est = None
                if reward_symbol.upper() in USD_SYMBOLS or _is_stable_addr(reward_token_addr):
                    usd_est = pending_human

                gauge_rewards_block = {
                    "reward_token": reward_token_addr,
                    "reward_symbol": reward_symbol,
                    "pending_raw": int(pending_raw),
                    "pending_amount": pending_human,
                    "pending_usd_est": float(usd_est) if usd_est is not None else None,
                }
        except Exception:
            gauge_rewards_block = {
                "reward_token": "",
                "reward_symbol": "",
                "pending_raw": 0,
                "pending_amount": 0,
                "pending_usd_est": 0,
            }
    else:
        gauge_rewards_block = {
            "reward_token": "",
            "reward_symbol": "",
            "pending_raw": 0,
            "pending_amount": 0,
            "pending_usd_est": 0,
        }

    # ---- Gauge reward balances (reward ERC20 held by the vault itself)
    gauge_reward_balances: Dict[str, Any] | None = None
    try:
        if gauge_rewards_block and "reward_token" in gauge_rewards_block:
            reward_token_addr = gauge_rewards_block["reward_token"]
            reward_symbol = gauge_rewards_block.get("reward_symbol", "REWARD")

            erc_reward = adapter.erc20(reward_token_addr)
            reward_dec = int(erc_reward.functions.decimals().call())

            in_vault_raw = int(erc_reward.functions.balanceOf(adapter.vault.address).call())
            in_vault_h = float(in_vault_raw) / (10 ** reward_dec)

            gauge_reward_balances = {
                "token": reward_token_addr,
                "symbol": reward_symbol,
                "decimals": reward_dec,
                "in_vault_raw": in_vault_raw,
                "in_vault": in_vault_h,
            }
    except Exception as e:
        gauge_reward_balances = {"error": f"reward_balance_read_failed: {str(e)}"}

    # ---- Position location ("none", "pool", "gauge")
    if token_id == 0:
        position_location = "none"
    else:
        position_location = "gauge" if is_staked else "pool"

    # ---- Cooldown computation (rebalance guard)
    now = adapter.w3.eth.get_block("latest").timestamp
    cooldown_remaining_seconds = int(last_rebalance + min_cd - now)
    cooldown_active = cooldown_remaining_seconds > 0

    # ---- Prices from slot0
    p_t1_t0 = sqrtPriceX96_to_price_t1_per_t0(sqrtP, dec0, dec1)
    p_t0_t1 = 0.0 if p_t1_t0 == 0 else 1.0 / p_t1_t0

    out_of_range = tick < lower or tick >= upper
    if out_of_range:
        dtick = (lower - tick) if tick < lower else (tick - upper)
        pct_outside_tick = _pct_from_dtick(dtick)
    else:
        pct_outside_tick = 0.0

    # ---- Uncollected fees (callStatic collect preview)
    fees0 = fees1 = 0
    if token_id != 0:
        fees0, fees1 = adapter.call_static_collect(token_id, adapter.vault.address)
    fees0_h = float(fees0) / (10 ** dec0)
    fees1_h = float(fees1) / (10 ** dec1)
    fees_usd = _value_usd(fees0_h, fees1_h, p_t1_t0, p_t0_t1, sym0, sym1, t0_addr, t1_addr)

    # ---- Token balances: idle and in-position
    erc0 = adapter.erc20(t0_addr)
    erc1 = adapter.erc20(t1_addr)

    bal0_idle_raw = int(erc0.functions.balanceOf(adapter.vault.address).call())
    bal1_idle_raw = int(erc1.functions.balanceOf(adapter.vault.address).call())

    amt0_pos_raw = amt1_pos_raw = 0
    if liq > 0:
        a0, a1 = adapter.amounts_in_position_now(lower, upper, liq)
        amt0_pos_raw, amt1_pos_raw = int(a0), int(a1)

    adj0_idle = bal0_idle_raw / (10 ** dec0)
    adj1_idle = bal1_idle_raw / (10 ** dec1)
    amt0_pos = amt0_pos_raw / (10 ** dec0)
    amt1_pos = amt1_pos_raw / (10 ** dec1)

    tot0 = adj0_idle + amt0_pos
    tot1 = adj1_idle + amt1_pos

    idle_usd = _value_usd(adj0_idle, adj1_idle, p_t1_t0, p_t0_t1, sym0, sym1, t0_addr, t1_addr)
    pos_usd = _value_usd(amt0_pos, amt1_pos, p_t1_t0, p_t0_t1, sym0, sym1, t0_addr, t1_addr)
    total_usd = _value_usd(tot0, tot1, p_t1_t0, p_t0_t1, sym0, sym1, t0_addr, t1_addr)

    # ---- Cumulative fees already collected (from state)
    cum_fees = st.get("fees_collected_cum", {"token0_raw": 0, "token1_raw": 0}) or {}
    cum0_raw = int(cum_fees.get("token0_raw", 0) or 0)
    cum1_raw = int(cum_fees.get("token1_raw", 0) or 0)
    cum0 = cum0_raw / (10 ** dec0)
    cum1 = cum1_raw / (10 ** dec1)
    cum_usd = _value_usd(cum0, cum1, p_t1_t0, p_t0_t1, sym0, sym1, t0_addr, t1_addr)

    # ---- Cumulative rewards already collected in USDC-equivalent units
    cum_rewards = st.get("rewards_usdc_cum", {}) or {}
    rewards_usdc_raw = int(cum_rewards.get("usdc_raw", 0))
    rewards_usdc = float(cum_rewards.get("usdc_human", 0.0))

    # ---- Baseline USD (initial snapshot)
    baseline = st.get("vault_initial_usd")
    if baseline is None:
        baseline = total_usd
        st["vault_initial_usd"] = baseline
        save_state(dex, alias, st)

    # ---- Build presentation models

    prices_panel = PricesPanel(
        current=PricesBlock(**prices_from_tick(tick, dec0, dec1)),
        lower=PricesBlock(**prices_from_tick(lower, dec0, dec1)),
        upper=PricesBlock(**prices_from_tick(upper, dec0, dec1)),
    )

    usd_panel = UsdPanelModel(
        usd_value=float(total_usd),
        delta_usd=float(total_usd - float(baseline)),
        baseline_usd=float(baseline),
    )

    holdings = HoldingsBlock(
        vault_idle=HoldingsSide(token0=adj0_idle, token1=adj1_idle, usd=idle_usd),
        in_position=HoldingsSide(token0=amt0_pos, token1=amt1_pos, usd=pos_usd),
        totals=HoldingsSide(token0=tot0, token1=tot1, usd=total_usd),
        decimals=HoldingsMeta(token0=dec0, token1=dec1),
        symbols={"token0": sym0, "token1": sym1},
        addresses={"token0": t0_addr, "token1": t1_addr},
    )

    fees_uncollected = FeesUncollected(
        token0=fees0_h,
        token1=fees1_h,
        usd=float(fees_usd),
        sym0=sym0,
        sym1=sym1,
    )

    fees_collected_cum = FeesCollectedCum(
        token0_raw=cum0_raw,
        token1_raw=cum1_raw,
        token0=cum0,
        token1=cum1,
        usd=float(cum_usd),
    )

    range_side = "inside" if not out_of_range else ("below" if tick < lower else "above")

    rewards_block = RewardsCollectedCum(
        usdc_raw=rewards_usdc_raw,
        usdc=rewards_usdc,
    )

    return StatusCore(
        tick=tick,
        lower=lower,
        upper=upper,
        spacing=tick_spacing,
        twap_ok=twap_ok,
        last_rebalance=last_rebalance,
        cooldown_remaining_seconds=cooldown_remaining_seconds,
        cooldown_active=cooldown_active,
        prices=prices_panel,
        gauge_rewards=gauge_rewards_block,
        gauge_reward_balances=gauge_reward_balances,
        rewards_collected_cum=rewards_block,
        fees_uncollected=fees_uncollected,
        fees_collected_cum=fees_collected_cum,
        out_of_range=out_of_range,
        pct_outside_tick=pct_outside_tick,
        usd_panel=usd_panel,
        range_side=range_side,
        sym0=sym0,
        sym1=sym1,
        holdings=holdings,
        has_gauge=has_gauge,
        gauge=gauge_addr,
        staked=is_staked,
        position_location=position_location,
    )
