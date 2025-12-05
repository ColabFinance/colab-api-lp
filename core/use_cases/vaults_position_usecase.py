# core/use_cases/vaults_position_usecase.py

import math
import time
import logging
from decimal import Decimal
from datetime import datetime

from fastapi import HTTPException
from web3 import Web3

from adapters.external.database import state_repo, vault_repo
from core.domain.models import (
    OpenRequest,
    RebalanceRequest,
    StatusCore,
    WithdrawRequest,
    CollectRequest,
    DepositRequest,
    StakeRequest,
    UnstakeRequest,
    ClaimRewardsRequest,
)
from core.services.tx_service import TxService
from core.services.exceptions import (
    TransactionBudgetExceededError,
    TransactionRevertedError,
)
from core.services.status_service import (
    USD_SYMBOLS,
    _is_usd_symbol,
    compute_status,
    price_to_tick,
    sqrtPriceX96_to_price_t1_per_t0,
)
from core.services.vault_adapter_service import get_adapter_for
from routes.utils import (
    _is_usd,
    estimate_eth_usd_from_pool,
    snapshot_status,
)


def open_position_uc(dex: str, alias: str, req: OpenRequest) -> dict:
    v = vault_repo.get_vault(dex, alias)
    if not v:
        raise HTTPException(404, "Unknown alias")
    if not v.get("pool"):
        raise HTTPException(400, "Vault has no pool set")

    state_repo.ensure_state_initialized(dex, alias, vault_address=v["address"])
    ad = get_adapter_for(
        dex,
        v["pool"],
        v.get("nfpm"),
        v["address"],
        v.get("rpc_url"),
        v.get("gauge"),
    )

    cons = ad.vault_constraints()
    meta = ad.pool_meta()
    dec0 = int(meta["dec0"])
    dec1 = int(meta["dec1"])
    sym0, sym1 = meta["sym0"], meta["sym1"]
    t0, t1 = meta["token0"], meta["token1"]
    spacing = int(meta.get("spacing") or cons.get("tickSpacing") or 0)

    from_addr = TxService(v.get("rpc_url")).sender_address()
    if cons.get("owner") and from_addr and cons["owner"].lower() != from_addr.lower():
        raise HTTPException(
            400,
            f"Sender is not vault owner. owner={cons['owner']} sender={from_addr}",
        )

    if cons.get("twapOk") is False:
        raise HTTPException(400, "TWAP guard not satisfied (twapOk=false).")

    if cons.get("minCooldown") and cons.get("lastRebalance"):
        if time.time() < cons["lastRebalance"] + cons["minCooldown"]:
            raise HTTPException(400, "Cooldown not finished yet (minCooldown).")

    bal0_raw, bal1_raw, _vault_meta = ad.vault_idle_balances()
    if bal0_raw == 0 and bal1_raw == 0:
        raise HTTPException(
            400,
            "Vault has no idle balances to mint liquidity (both token balances are zero).",
        )

    lower_tick = req.lower_tick
    upper_tick = req.upper_tick

    if lower_tick is None or upper_tick is None:
        if req.lower_price is None or req.upper_price is None:
            raise HTTPException(
                400,
                "You must provide either (lower_tick and upper_tick) OR (lower_price and upper_price).",
            )

        sqrtP, spot_tick = ad.slot0()
        p_ref = sqrtPriceX96_to_price_t1_per_t0(sqrtP, dec0, dec1)

        def _canon_to_t1_per_t0(p_in: float) -> float:
            if p_in <= 0:
                raise HTTPException(400, "Price must be positive.")
            token0_is_usd = _is_usd(sym0, t0)
            token1_is_usd = _is_usd(sym1, t1)

            p = float(p_in)
            if token0_is_usd and not token1_is_usd:
                if p_ref > 0:
                    if abs(math.log10(p / max(p_ref, 1e-18))) > 4:
                        return 1.0 / p
                if p > 50:
                    return 1.0 / p

            if p_ref > 0 and abs(math.log10(p / max(p_ref, 1e-18))) > 6:
                inv = 1.0 / p
                return inv if abs(math.log10(inv / p_ref)) < abs(
                    math.log10(p / p_ref)
                ) else p

            return p

        lp = _canon_to_t1_per_t0(float(req.lower_price))
        up = _canon_to_t1_per_t0(float(req.upper_price))

        lower_tick = price_to_tick(lp, dec0, dec1)
        upper_tick = price_to_tick(up, dec0, dec1)

    if lower_tick > upper_tick:
        lower_tick, upper_tick = upper_tick, lower_tick

    if spacing:
        if lower_tick % spacing != 0:
            lower_tick = int(round(lower_tick / spacing) * spacing)
        if upper_tick % spacing != 0:
            upper_tick = int(round(upper_tick / spacing) * spacing)

    width = abs(int(upper_tick) - int(lower_tick))
    if cons.get("minWidth") and width < cons["minWidth"]:
        raise HTTPException(
            400,
            f"Width too small: {width} < minWidth={cons['minWidth']}.",
        )
    if cons.get("maxWidth") and width > cons["maxWidth"]:
        raise HTTPException(
            400,
            f"Width too large: {width} > maxWidth={cons['maxWidth']}.",
        )

    before = snapshot_status(ad, dex, alias)

    fn = ad.fn_open(int(lower_tick), int(upper_tick))

    eth_usd_hint = estimate_eth_usd_from_pool(ad)
    max_budget_usd = req.max_budget_usd

    txs = TxService(v.get("rpc_url"))
    try:
        send_res = txs.send(
            fn,
            wait=True,
            gas_strategy="buffered",
            max_gas_usd=max_budget_usd,
            eth_usd_hint=eth_usd_hint,
        )
    except TransactionBudgetExceededError as e:
        payload = {
            "tx_hash": None,
            "broadcasted": False,
            "status": None,
            "error_type": "BUDGET_EXCEEDED",
            "error_msg": "Gas cost upper bound is above allowed max_gas_usd",
            "budget_info": {
                "usd_budget": e.usd_budget,
                "usd_estimated_upper_bound": e.usd_estimated,
                "eth_usd_hint": e.eth_usd,
                "gas_price_wei": e.gas_price_wei,
                "est_gas_limit": e.est_gas_limit,
            },
        }
        state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "open_initial_failed_budget",
                "payload": payload,
            },
        )
        raise HTTPException(status_code=400, detail=payload)

    except TransactionRevertedError as e:
        rcpt = e.receipt or {}
        gas_used = int(rcpt.get("gasUsed") or 0)
        eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

        gas_eth = gas_usd = None
        if gas_used and eff_price_wei and eth_usd_hint:
            gas_eth = float(
                (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
            )
            gas_usd = gas_eth * float(eth_usd_hint)

        payload = {
            "tx_hash": e.tx_hash,
            "broadcasted": True,
            "status": 0,
            "error_type": "ONCHAIN_REVERT",
            "error_msg": e.msg,
            "receipt": rcpt,
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
        }

        state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "open_initial_failed_revert",
                "payload": payload,
            },
        )

        raise HTTPException(status_code=502, detail=payload)

    rcpt = send_res["receipt"] or {}
    gas_used = int(rcpt.get("gasUsed") or 0)
    eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

    gas_eth = gas_usd = None
    if gas_used and eff_price_wei and eth_usd_hint:
        gas_eth = float(
            (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
        )
        gas_usd = gas_eth * float(eth_usd_hint)

    after = snapshot_status(ad, dex, alias)

    state_repo.append_history(
        dex,
        alias,
        "exec_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "mode": "open_initial",
            "lower_tick": int(lower_tick),
            "upper_tick": int(upper_tick),
            "tx": send_res["tx_hash"],
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
            "gas_budget_check": send_res.get("gas_budget_check"),
            "send_res": send_res,
        },
    )

    return {
        "tx": send_res["tx_hash"],
        "range_used": {
            "lower_tick": int(lower_tick),
            "upper_tick": int(upper_tick),
            "width_ticks": width,
            "spacing": spacing,
            "lower_price": float(req.lower_price)
            if req.lower_price is not None
            else None,
            "upper_price": float(req.upper_price)
            if req.upper_price is not None
            else None,
        },
        "gas_used": gas_used,
        "effective_gas_price_wei": eff_price_wei,
        "gas_eth": gas_eth,
        "gas_usd": gas_usd,
        "budget": send_res.get("gas_budget_check"),
        "before": before,
        "after": after,
        "send_res": send_res,
    }


def rebalance_caps_uc(dex: str, alias: str, req: RebalanceRequest) -> dict:
    v = vault_repo.get_vault(dex, alias)
    if not v:
        raise HTTPException(404, "Unknown alias")
    if not v.get("pool"):
        raise HTTPException(400, "Vault has no pool set")

    state_repo.ensure_state_initialized(dex, alias, vault_address=v["address"])
    ad = get_adapter_for(
        dex,
        v["pool"],
        v.get("nfpm"),
        v["address"],
        v.get("rpc_url"),
        v.get("gauge"),
    )

    cons = ad.vault_constraints()
    meta = ad.pool_meta()
    dec0 = int(meta["dec0"])
    dec1 = int(meta["dec1"])
    spacing = int(meta["spacing"])

    from_addr = TxService(v.get("rpc_url")).sender_address()
    if cons.get("owner") and from_addr and cons["owner"].lower() != from_addr.lower():
        raise HTTPException(
            400,
            f"Sender is not vault owner. owner={cons['owner']} sender={from_addr}",
        )

    if cons.get("twapOk") is False:
        raise HTTPException(400, "TWAP guard not satisfied (twapOk=false).")
    if cons.get("minCooldown") and cons.get("lastRebalance"):
        if time.time() < cons["lastRebalance"] + cons["minCooldown"]:
            raise HTTPException(400, "Cooldown not finished yet (minCooldown).")

    lower_tick = req.lower_tick
    upper_tick = req.upper_tick

    if lower_tick is None or upper_tick is None:
        if req.lower_price is None or req.upper_price is None:
            raise HTTPException(
                400,
                "You must provide either (lower_tick and upper_tick) OR (lower_price and upper_price).",
            )
        lower_tick = price_to_tick(float(req.lower_price), dec0, dec1)
        upper_tick = price_to_tick(float(req.upper_price), dec0, dec1)

    if lower_tick > upper_tick:
        lower_tick, upper_tick = upper_tick, lower_tick

    if lower_tick % spacing != 0:
        lower_tick = int(round(lower_tick / spacing) * spacing)
    if upper_tick % spacing != 0:
        upper_tick = int(round(upper_tick / spacing) * spacing)

    width = abs(int(upper_tick) - int(lower_tick))
    if cons.get("minWidth") and width < cons["minWidth"]:
        raise HTTPException(
            400,
            f"Width too small: {width} < minWidth={cons['minWidth']}.",
        )
    if cons.get("maxWidth") and width > cons["maxWidth"]:
        raise HTTPException(
            400,
            f"Width too large: {width} > maxWidth={cons['maxWidth']}.",
        )

    cap0_raw = cap1_raw = None
    if req.cap0 is not None:
        cap0_raw = int(float(req.cap0) * (10**dec0))
    if req.cap1 is not None:
        cap1_raw = int(float(req.cap1) * (10**dec1))

    before = snapshot_status(ad, dex, alias)

    fn = ad.fn_rebalance_caps(lower_tick, upper_tick, cap0_raw, cap1_raw)
    txs = TxService(v.get("rpc_url"))
    try:
        send_res = txs.send(fn, wait=True, gas_strategy="buffered")
    except TransactionRevertedError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "reverted_on_chain",
                "tx": e.tx_hash,
                "receipt": e.receipt,
                "hint": "Likely out-of-gas or slippage/guard.",
            },
        )

    tx_hash = send_res["tx_hash"]
    rcpt = send_res["receipt"] or {}

    gas_limit_used = send_res.get("gas_limit_used")
    gas_used = int(rcpt.get("gasUsed") or 0)
    eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)
    gas_eth = gas_usd = None
    if gas_used and eff_price_wei:
        gas_eth = float(
            (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
        )
        meta2 = ad.pool_meta()
        dec0b, dec1b = int(meta2["dec0"]), int(meta2["dec1"])
        sym0b, sym1b = str(meta2["sym0"]).upper(), str(meta2["sym1"]).upper()
        sqrtPb, _ = ad.slot0()
        p_t1_t0b = sqrtPriceX96_to_price_t1_per_t0(sqrtPb, dec0b, dec1b)
        if sym1b in USD_SYMBOLS and sym0b in {"WETH", "ETH"}:
            gas_usd = gas_eth * p_t1_t0b
        elif sym0b in USD_SYMBOLS and sym1b in {"WETH", "ETH"}:
            gas_usd = gas_eth * (0 if p_t1_t0b == 0 else 1.0 / p_t1_t0b)

    after = snapshot_status(ad, dex, alias)

    state_repo.append_history(
        dex,
        alias,
        "exec_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "mode": "rebalance_caps",
            "lower_tick": lower_tick,
            "upper_tick": upper_tick,
            "lower_price": float(req.lower_price)
            if req.lower_price is not None
            else None,
            "upper_price": float(req.upper_price)
            if req.upper_price is not None
            else None,
            "cap0": req.cap0,
            "cap1": req.cap1,
            "tx": tx_hash,
            "gas_used": gas_used,
            "gas_limit_used": gas_limit_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
        },
    )

    return {
        "tx": tx_hash,
        "range_used": {
            "lower_tick": lower_tick,
            "upper_tick": upper_tick,
            "width_ticks": width,
            "spacing": spacing,
            "lower_price": float(req.lower_price)
            if req.lower_price is not None
            else None,
            "upper_price": float(req.upper_price)
            if req.upper_price is not None
            else None,
        },
        "gas_used": gas_used,
        "gas_limit_used": gas_limit_used,
        "effective_gas_price_wei": eff_price_wei,
        "gas_eth": gas_eth,
        "gas_usd": gas_usd,
        "before": before,
        "after": after,
    }


def withdraw_uc(dex: str, alias: str, req: WithdrawRequest) -> dict:
    v = vault_repo.get_vault(dex, alias)
    if not v:
        raise HTTPException(404, "Unknown alias")
    if not v.get("pool"):
        raise HTTPException(400, "Vault has no pool set")

    state_repo.ensure_state_initialized(dex, alias, vault_address=v["address"])
    ad = get_adapter_for(
        dex,
        v["pool"],
        v.get("nfpm"),
        v["address"],
        v.get("rpc_url"),
        v.get("gauge"),
    )

    vstate = ad.vault_state()
    if vstate.get("staked") and req.mode == "pool":
        raise HTTPException(
            400,
            detail={
                "error": "POSITION_STAKED",
                "message": "NFT está staked. Chame /unstake antes de /withdraw (mode='pool').",
            },
        )

    eth_usd_hint = estimate_eth_usd_from_pool(ad)
    max_budget_usd = req.max_budget_usd

    txs = TxService(v.get("rpc_url"))

    before = snapshot_status(ad, dex, alias)

    if req.mode == "pool":
        fn = ad.fn_exit()
    else:
        to_addr = txs.sender_address()
        fn = ad.fn_exit_withdraw(to_addr)

    try:
        send_res = txs.send(
            fn,
            wait=True,
            gas_strategy="buffered",
            max_gas_usd=max_budget_usd,
            eth_usd_hint=eth_usd_hint,
        )
    except TransactionBudgetExceededError as e:
        payload = {
            "tx_hash": None,
            "broadcasted": False,
            "status": None,
            "error_type": "BUDGET_EXCEEDED",
            "error_msg": "Gas cost upper bound is above allowed max_gas_usd",
            "budget_info": {
                "usd_budget": e.usd_budget,
                "usd_estimated_upper_bound": e.usd_estimated,
                "eth_usd_hint": e.eth_usd,
                "gas_price_wei": e.gas_price_wei,
                "est_gas_limit": e.est_gas_limit,
            },
        }
        state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "exit_failed_budget",
                "payload": payload,
            },
        )
        raise HTTPException(status_code=400, detail=payload)

    except TransactionRevertedError as e:
        rcpt = e.receipt or {}
        gas_used = int(rcpt.get("gasUsed") or 0)
        eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

        gas_eth = gas_usd = None
        if gas_used and eff_price_wei and eth_usd_hint:
            gas_eth = float(
                (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
            )
            gas_usd = gas_eth * float(eth_usd_hint)

        payload = {
            "tx_hash": e.tx_hash,
            "broadcasted": True,
            "status": 0,
            "error_type": "ONCHAIN_REVERT",
            "error_msg": e.msg,
            "receipt": rcpt,
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
        }

        state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "exit_failed_revert",
                "payload": payload,
            },
        )

        raise HTTPException(status_code=502, detail=payload)

    rcpt = send_res["receipt"] or {}
    gas_used = int(rcpt.get("gasUsed") or 0)
    eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

    gas_eth = gas_usd = None
    if gas_used and eff_price_wei and eth_usd_hint:
        gas_eth = float(
            (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
        )
        gas_usd = gas_eth * float(eth_usd_hint)

    after = snapshot_status(ad, dex, alias)

    state_repo.append_history(
        dex,
        alias,
        "exec_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "mode": ("exit_pool" if req.mode == "pool" else "exit_all"),
            "to": txs.sender_address() if req.mode != "pool" else None,
            "tx": send_res["tx_hash"],
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
            "gas_budget_check": send_res.get("gas_budget_check"),
            "send_res": send_res,
        },
    )

    return {
        "tx": send_res["tx_hash"],
        "mode": ("exit" if req.mode == "pool" else "exit_withdraw"),
        "gas_used": gas_used,
        "effective_gas_price_wei": eff_price_wei,
        "gas_eth": gas_eth,
        "gas_usd": gas_usd,
        "budget": send_res.get("gas_budget_check"),
        "before": before,
        "after": after,
        "send_res": send_res,
    }


def collect_uc(dex: str, alias: str, req: CollectRequest) -> dict:
    v = vault_repo.get_vault(dex, alias)
    if not v:
        raise HTTPException(404, "Unknown alias")
    if not v.get("pool"):
        raise HTTPException(400, "Vault has no pool set")

    state_repo.ensure_state_initialized(dex, alias, vault_address=v["address"])
    ad = get_adapter_for(
        dex,
        v["pool"],
        v.get("nfpm"),
        v["address"],
        v.get("rpc_url"),
        v.get("gauge"),
    )

    before = snapshot_status(ad, dex, alias)

    snap: StatusCore = compute_status(ad, dex, alias)
    meta = ad.pool_meta()
    dec0, dec1 = int(meta["dec0"]), int(meta["dec1"])
    sym0, sym1 = meta["sym0"], meta["sym1"]

    p_t1_t0 = float(snap.prices.current.p_t1_t0)
    p_t0_t1 = float(snap.prices.current.p_t0_t1)

    vstate = ad.vault_state()
    token_id = int(vstate.get("tokenId", 0) or 0)
    if token_id == 0:
        raise HTTPException(400, "No active position to collect fees from.")

    fees0_raw, fees1_raw = ad.call_static_collect(token_id, ad.vault.address)

    pre_fees0 = float(fees0_raw) / (10**dec0)
    pre_fees1 = float(fees1_raw) / (10**dec1)

    if _is_usd_symbol(sym1):
        pre_fees_usd = pre_fees0 * p_t1_t0 + pre_fees1
    elif _is_usd_symbol(sym0):
        pre_fees_usd = pre_fees1 * p_t0_t1 + pre_fees0
    else:
        pre_fees_usd = pre_fees0 * p_t1_t0 + pre_fees1

    eth_usd_hint = estimate_eth_usd_from_pool(ad)
    max_budget_usd = req.max_budget_usd

    txs = TxService(v.get("rpc_url"))
    fn = ad.fn_collect()
    try:
        send_res = txs.send(
            fn,
            wait=True,
            gas_strategy="buffered",
            max_gas_usd=max_budget_usd,
            eth_usd_hint=eth_usd_hint,
        )
    except TransactionBudgetExceededError as e:
        payload = {
            "tx_hash": None,
            "broadcasted": False,
            "status": None,
            "error_type": "BUDGET_EXCEEDED",
            "error_msg": "Gas cost upper bound is above allowed max_gas_usd",
            "budget_info": {
                "usd_budget": e.usd_budget,
                "usd_estimated_upper_bound": e.usd_estimated,
                "eth_usd_hint": e.eth_usd,
                "gas_price_wei": e.gas_price_wei,
                "est_gas_limit": e.est_gas_limit,
            },
        }
        state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "collect_failed_budget",
                "payload": payload,
            },
        )
        raise HTTPException(status_code=400, detail=payload)

    except TransactionRevertedError as e:
        rcpt = e.receipt or {}
        gas_used = int(rcpt.get("gasUsed") or 0)
        eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

        gas_eth = gas_usd = None
        if gas_used and eff_price_wei and eth_usd_hint:
            gas_eth = float(
                (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
            )
            gas_usd = gas_eth * float(eth_usd_hint)

        payload = {
            "tx_hash": e.tx_hash,
            "broadcasted": True,
            "status": 0,
            "error_type": "ONCHAIN_REVERT",
            "error_msg": e.msg,
            "receipt": rcpt,
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
        }

        state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "collect_failed_revert",
                "payload": payload,
            },
        )

        raise HTTPException(status_code=502, detail=payload)

    rcpt = send_res["receipt"] or {}
    gas_used = int(rcpt.get("gasUsed") or 0)
    eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

    gas_eth = gas_usd = None
    if gas_used and eff_price_wei and eth_usd_hint:
        gas_eth = float(
            (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
        )
        gas_usd = gas_eth * float(eth_usd_hint)

    after = snapshot_status(ad, dex, alias)

    state_repo.add_collected_fees_snapshot(
        dex,
        alias,
        fees0_raw=int(fees0_raw),
        fees1_raw=int(fees1_raw),
        fees_usd_est=float(pre_fees_usd),
    )
    state_repo.append_history(
        dex,
        alias,
        "collect_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "fees0_raw": int(fees0_raw),
            "fees1_raw": int(fees1_raw),
            "fees_usd_est": float(pre_fees_usd),
            "tx": send_res["tx_hash"],
        },
    )
    state_repo.append_history(
        dex,
        alias,
        "exec_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "mode": "collect",
            "tx": send_res["tx_hash"],
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
            "gas_budget_check": send_res.get("gas_budget_check"),
            "send_res": send_res,
        },
    )

    return {
        "tx": send_res["tx_hash"],
        "collected_preview": {
            "token0": pre_fees0,
            "token1": pre_fees1,
            "usd_est": float(pre_fees_usd),
        },
        "gas_used": gas_used,
        "effective_gas_price_wei": eff_price_wei,
        "gas_eth": gas_eth,
        "gas_usd": gas_usd,
        "budget": send_res.get("gas_budget_check"),
        "before": before,
        "after": after,
        "send_res": send_res,
    }


def deposit_uc(dex: str, alias: str, req: DepositRequest) -> dict:
    v = vault_repo.get_vault(dex, alias)
    if not v:
        raise HTTPException(404, "Unknown alias")
    if not v.get("pool"):
        raise HTTPException(400, "Vault has no pool set")

    state_repo.ensure_state_initialized(dex, alias, vault_address=v["address"])
    ad = get_adapter_for(
        dex,
        v["pool"],
        v.get("nfpm"),
        v["address"],
        v.get("rpc_url"),
        v.get("gauge"),
    )

    tok = Web3.to_checksum_address(req.token)
    dec = ad.erc20(tok).functions.decimals().call()
    amount_raw = int(float(req.amount) * (10**int(dec)))

    before = snapshot_status(ad, dex, alias)

    txs = TxService(v.get("rpc_url"))
    fn = ad.fn_deposit_erc20(tok, amount_raw)
    try:
        send_res = txs.send(fn, wait=True, gas_strategy="buffered")
    except TransactionRevertedError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "reverted_on_chain",
                "tx": e.tx_hash,
                "receipt": e.receipt,
                "hint": "Likely out-of-gas or slippage/guard.",
            },
        )

    tx_hash = send_res["tx_hash"]
    rcpt = send_res["receipt"] or {}

    gas_limit_used = send_res.get("gas_limit_used")
    gas_used = int(rcpt.get("gasUsed") or 0)
    eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)
    gas_eth = gas_usd = None
    if gas_used and eff_price_wei:
        gas_eth = float(
            (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
        )
        meta2 = ad.pool_meta()
        dec0b, dec1b = int(meta2["dec0"]), int(meta2["dec1"])
        sym0b, sym1b = str(meta2["sym0"]).upper(), str(meta2["sym1"]).upper()
        sqrtPb, _ = ad.slot0()
        p_t1_t0b = sqrtPriceX96_to_price_t1_per_t0(sqrtPb, dec0b, dec1b)
        if sym1b in USD_SYMBOLS and sym0b in {"WETH", "ETH"}:
            gas_usd = gas_eth * p_t1_t0b
        elif sym0b in USD_SYMBOLS and sym1b in {"WETH", "ETH"}:
            gas_usd = gas_eth * (0 if p_t1_t0b == 0 else 1.0 / p_t1_t0b)

    after = snapshot_status(ad, dex, alias)

    state_repo.append_history(
        dex,
        alias,
        "deposit_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "token": tok,
            "amount_human": float(req.amount),
            "amount_raw": int(amount_raw),
            "tx": tx_hash,
            "gas_used": gas_used,
            "gas_limit_used": gas_limit_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
        },
    )
    state_repo.append_history(
        dex,
        alias,
        "exec_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "mode": "deposit",
            "token": tok,
            "amount_human": float(req.amount),
            "tx": tx_hash,
            "gas_used": gas_used,
            "gas_limit_used": gas_limit_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
        },
    )

    return {
        "tx": tx_hash,
        "token": tok,
        "amount_human": float(req.amount),
        "amount_raw": int(amount_raw),
        "gas_used": gas_used,
        "gas_limit_used": gas_limit_used,
        "effective_gas_price_wei": eff_price_wei,
        "gas_eth": gas_eth,
        "gas_usd": gas_usd,
        "before": before,
        "after": after,
    }


def stake_nft_uc(dex: str, alias: str, req: StakeRequest) -> dict:
    v = vault_repo.get_vault(dex, alias)
    if not v:
        raise HTTPException(404, "Unknown alias")
    if not v.get("pool"):
        raise HTTPException(400, "Vault has no pool set")

    ad = get_adapter_for(
        dex,
        v["pool"],
        v.get("nfpm"),
        v["address"],
        v.get("rpc_url"),
        v.get("gauge"),
    )

    before = snapshot_status(ad, dex, alias)

    eth_usd_hint = estimate_eth_usd_from_pool(ad)
    max_budget_usd = req.max_budget_usd

    if dex == "aerodrome":
        fn = ad.fn_stake_nft()
    elif dex == "pancake":
        from config import get_settings as _get_settings

        mc = _get_settings().PANCAKE_MASTERCHEF_V3
        if not mc:
            raise HTTPException(500, "PANCAKE_MASTERCHEF_V3 not configured")
        fn = ad.fn_stake()
    else:
        raise HTTPException(400, "Stake not supported for this DEX")

    txs = TxService(v.get("rpc_url"))
    try:
        send_res = txs.send(
            fn,
            wait=True,
            gas_strategy="buffered",
            max_gas_usd=max_budget_usd,
            eth_usd_hint=eth_usd_hint,
        )
    except TransactionBudgetExceededError as e:
        payload = {
            "tx_hash": None,
            "broadcasted": False,
            "status": None,
            "error_type": "BUDGET_EXCEEDED",
            "error_msg": "Gas cost upper bound is above allowed max_gas_usd",
            "budget_info": {
                "usd_budget": e.usd_budget,
                "usd_estimated_upper_bound": e.usd_estimated,
                "eth_usd_hint": e.eth_usd,
                "gas_price_wei": e.gas_price_wei,
                "est_gas_limit": e.est_gas_limit,
            },
        }
        state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "stake_gauge_failed_budget",
                "payload": payload,
            },
        )
        raise HTTPException(status_code=400, detail=payload)

    except TransactionRevertedError as e:
        rcpt = e.receipt or {}
        gas_used = int(rcpt.get("gasUsed") or 0)
        eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

        gas_eth = gas_usd = None
        if gas_used and eff_price_wei and eth_usd_hint:
            gas_eth = float(
                (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
            )
            gas_usd = gas_eth * float(eth_usd_hint)

        payload = {
            "tx_hash": e.tx_hash,
            "broadcasted": True,
            "status": 0,
            "error_type": "ONCHAIN_REVERT",
            "error_msg": e.msg,
            "receipt": rcpt,
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
        }

        state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "stake_gauge_failed_revert",
                "payload": payload,
            },
        )

        raise HTTPException(status_code=502, detail=payload)

    rcpt = send_res["receipt"] or {}
    gas_used = int(rcpt.get("gasUsed") or 0)
    eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

    gas_eth = gas_usd = None
    if gas_used and eff_price_wei and eth_usd_hint:
        gas_eth = float(
            (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
        )
        gas_usd = gas_eth * float(eth_usd_hint)

    after = snapshot_status(ad, dex, alias)

    state_repo.append_history(
        dex,
        alias,
        "exec_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "mode": "stake_gauge",
            "tx": send_res["tx_hash"],
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
            "gas_budget_check": send_res.get("gas_budget_check"),
            "send_res": send_res,
        },
    )

    return {
        "tx": send_res["tx_hash"],
        "gas_used": gas_used,
        "effective_gas_price_wei": eff_price_wei,
        "gas_eth": gas_eth,
        "gas_usd": gas_usd,
        "budget": send_res.get("gas_budget_check"),
        "before": before,
        "after": after,
        "send_res": send_res,
    }


def unstake_nft_uc(dex: str, alias: str, req: UnstakeRequest) -> dict:
    v = vault_repo.get_vault(dex, alias)
    if not v:
        raise HTTPException(404, "Unknown alias")
    if not v.get("pool"):
        raise HTTPException(400, "Vault has no pool set")

    ad = get_adapter_for(
        dex,
        v["pool"],
        v.get("nfpm"),
        v["address"],
        v.get("rpc_url"),
        v.get("gauge"),
    )
    txs = TxService(v.get("rpc_url"))

    if dex == "aerodrome":
        fn = ad.fn_unstake_nft()
    elif dex == "pancake":
        from config import get_settings as _get_settings

        mc = _get_settings().PANCAKE_MASTERCHEF_V3
        if not mc:
            raise HTTPException(500, "PANCAKE_MASTERCHEF_V3 not configured")
        fn = ad.fn_unstake()
    else:
        raise HTTPException(400, "Unstake not supported for this DEX")

    before = snapshot_status(ad, dex, alias)

    eth_usd_hint = estimate_eth_usd_from_pool(ad)
    max_budget_usd = req.max_budget_usd

    try:
        send_res = txs.send(
            fn,
            wait=True,
            gas_strategy="buffered",
            max_gas_usd=max_budget_usd,
            eth_usd_hint=eth_usd_hint,
        )
    except TransactionBudgetExceededError as e:
        payload = {
            "tx_hash": None,
            "broadcasted": False,
            "status": None,
            "error_type": "BUDGET_EXCEEDED",
            "error_msg": "Gas cost upper bound is above allowed max_gas_usd",
            "budget_info": {
                "usd_budget": e.usd_budget,
                "usd_estimated_upper_bound": e.usd_estimated,
                "eth_usd_hint": e.eth_usd,
                "gas_price_wei": e.gas_price_wei,
                "est_gas_limit": e.est_gas_limit,
            },
        }
        state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "unstake_gauge_failed_budget",
                "payload": payload,
            },
        )
        raise HTTPException(status_code=400, detail=payload)

    except TransactionRevertedError as e:
        rcpt = e.receipt or {}
        gas_used = int(rcpt.get("gasUsed") or 0)
        eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

        gas_eth = gas_usd = None
        if gas_used and eff_price_wei and eth_usd_hint:
            gas_eth = float(
                (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
            )
            gas_usd = gas_eth * float(eth_usd_hint)

        payload = {
            "tx_hash": e.tx_hash,
            "broadcasted": True,
            "status": 0,
            "error_type": "ONCHAIN_REVERT",
            "error_msg": e.msg,
            "receipt": rcpt,
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
        }

        state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "unstake_gauge_failed_revert",
                "payload": payload,
            },
        )

        raise HTTPException(status_code=502, detail=payload)

    rcpt = send_res["receipt"] or {}
    gas_used = int(rcpt.get("gasUsed") or 0)
    eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

    gas_eth = gas_usd = None
    if gas_used and eff_price_wei and eth_usd_hint:
        gas_eth = float(
            (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
        )
        gas_usd = gas_eth * float(eth_usd_hint)

    after = snapshot_status(ad, dex, alias)

    state_repo.append_history(
        dex,
        alias,
        "exec_history",
        {
            "ts": datetime.utcnow().isoformat(),
            "mode": "unstake_gauge",
            "tx": send_res["tx_hash"],
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
            "gas_budget_check": send_res.get("gas_budget_check"),
            "send_res": send_res,
        },
    )

    return {
        "tx": send_res["tx_hash"],
        "gas_used": gas_used,
        "effective_gas_price_wei": eff_price_wei,
        "gas_eth": gas_eth,
        "gas_usd": gas_usd,
        "budget": send_res.get("gas_budget_check"),
        "before": before,
        "after": after,
        "send_res": send_res,
    }


def claim_rewards_uc(dex: str, alias: str, req: ClaimRewardsRequest) -> dict:
    """
    TODO: Move the current body of claim_rewards (from your original vaults.py)
    into this function, following the same pattern as stake/unstake.

    Keeping a stub here so the HTTP route can call this usecase.
    """
    raise NotImplementedError(
        "Move the existing claim_rewards logic from the old routes/vaults.py into claim_rewards_uc."
    )
