# core/domain/usecases/vaults_swap_usecase.py

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from web3 import Web3

from config import get_settings
from core.domain.swap import SwapExactInRequest, SwapQuoteRequest
from core.services.tx_service import (
    TxService,
    TransactionBudgetExceededError,
    TransactionRevertedError,
)
from adapters.external.database import state_repo, vault_repo
from core.services.status_service import (

    sqrtPriceX96_to_price_t1_per_t0,
    _value_usd,
    USD_SYMBOLS,
)
from core.services.vault_adapter_service import get_adapter_for
from routes.utils import (
    _is_usd,
    estimate_eth_usd_from_pool,
    tick_spacing_candidates,
    snapshot_status,
    resolve_pool_from_vault,
    snapshot_status,
    estimate_eth_usd_from_pool,
)


class VaultsSwapUseCase:
    """
    Use case responsible for handling swap-related operations for vaults
    across multiple DEXes (Uniswap v3, Aerodrome, Pancake v3).

    This class encapsulates all business rules for quoting and executing swaps
    from the vault contracts, keeping adapters and repositories injected so
    the HTTP layer remains thin and declarative.

    The methods here keep the on-chain logic as close as possible to your
    original implementation, only reorganized into a clean use-case layer.
    """

    def __init__(
        self,
    ) -> None:
        """
        Initialize the VaultsSwapUseCase.

        Args:
            vault_repo: Repository used to resolve vault configuration
                (DEX, pool, NFPM, gauge, RPC URL, etc.) by alias.
            state_repo: Repository responsible for tracking vault state,
                execution history, rewards snapshots and collected fees.

        Note:
            Settings (addresses for routers/quoters) are loaded lazily via
            `get_settings()` so they remain environment-driven.
        """
        self._vault_repo = vault_repo
        self._state_repo = state_repo

    # -------------------------------------------------------------------------
    # UNISWAP v3
    # -------------------------------------------------------------------------

    def uniswap_swap_quote(self, alias: str, req: SwapQuoteRequest) -> dict[str, Any]:
        """
        Quote an exact-in swap for a vault using Uniswap v3.

        This method:
          1) Resolves the vault by alias, regardless of its underlying DEX.
          2) Resolves the Uniswap pool to be used (default or override).
          3) Validates that token_in/token_out are part of the chosen pool.
          4) Computes raw amounts using the vault's ERC20 decimals.
          5) Uses the Uniswap V3 Quoter to obtain the best feasible route.
          6) Estimates gas in ETH and converts to USD using the swap pool price.
          7) Returns a fully detailed quote object (raw/human amounts, gas,
             price impact proxy and pool metadata).

        Args:
            alias: Human-friendly alias of the vault.
            req: SwapQuoteRequest with token addresses, amount_in (human),
                optional fee override, sqrt price limit and pool override.

        Returns:
            A dictionary with:
                - best_fee
                - best_tick_spacing (alias for fee)
                - amount_in_raw / amount_out_raw
                - amount_in / amount_out (human)
                - sqrtPriceX96_after
                - initialized_ticks_crossed
                - gas_estimate / gas_eth / gas_usd / gas_price_gwei
                - value_at_sqrt_after_usd
                - pool_used / pool_symbols

        Raises:
            HTTPException:
                - 404 if the alias is unknown.
                - 500 if UNI_V3_QUOTER is not configured.
                - 400 if tokens are not in the pool, amount_in <= 0 or if
                  no fee tier produced a valid route.
        """
        dex_for_quote = "uniswap"

        vault_dex, v = self._vault_repo.get_vault_any(alias)
        if not v:
            raise HTTPException(404, "Unknown alias (not found in uniswap or aerodrome)")

        s = get_settings()
        if not s.UNI_V3_QUOTER:
            raise HTTPException(500, "UNI_V3_QUOTER not configured")

        ad_vault = get_adapter_for(
            vault_dex, v["pool"], v.get("nfpm"), v["address"], v.get("rpc_url"), v.get("gauge")
        )

        pool_uni = resolve_pool_from_vault(v, req.pool_override)
        ad_uni = get_adapter_for(
            dex_for_quote,
            pool_uni,
            None,
            v["address"],
            v.get("rpc_url"),
        )
        quoter = ad_uni.quoter(s.UNI_V3_QUOTER)

        meta_uni = ad_uni.pool_meta()
        pool_t0 = Web3.to_checksum_address(meta_uni["token0"])
        pool_t1 = Web3.to_checksum_address(meta_uni["token1"])
        pool_fee = int(ad_uni.uni_pool_fee(pool_uni))
        t0_sym, t1_sym = meta_uni["sym0"], meta_uni["sym1"]

        token_in = Web3.to_checksum_address(req.token_in)
        token_out = Web3.to_checksum_address(req.token_out)

        if {token_in, token_out} != {pool_t0, pool_t1}:
            raise HTTPException(
                400,
                {
                    "error": "TOKENS_NOT_IN_POOL",
                    "hint": "Check if you are using the correct USDC/USDbC or another AERO address.",
                    "pool_used": pool_uni,
                    "pool_token0": pool_t0,
                    "pool_token1": pool_t1,
                    "pool_symbols": [t0_sym, t1_sym],
                    "req_token_in": token_in,
                    "req_token_out": token_out,
                },
            )

        dec_in = int(ad_vault.erc20(token_in).functions.decimals().call())
        dec_out = int(ad_vault.erc20(token_out).functions.decimals().call())

        amount_in_raw = int(float(req.amount_in) * (10**dec_in))
        if amount_in_raw <= 0:
            raise HTTPException(400, "amount_in must be > 0")

        fee_candidates = [pool_fee]

        best: Optional[dict[str, Any]] = None
        last_exc: Optional[str] = None
        for fee in fee_candidates:
            params = {
                "tokenIn": token_in,
                "tokenOut": token_out,
                "amountIn": int(amount_in_raw),
                "fee": int(fee),
                "sqrtPriceLimitX96": int(req.sqrt_price_limit_x96 or 0),
            }
            try:
                amount_out_raw, sqrt_after, ticks_crossed, gas_est = (
                    quoter.functions.quoteExactInputSingle(params).call()
                )
                if int(amount_out_raw) > 0 and (
                    not best or int(amount_out_raw) > best["amount_out_raw"]
                ):
                    best = {
                        "fee": int(fee),
                        "amount_out_raw": int(amount_out_raw),
                        "sqrt_after": int(sqrt_after),
                        "ticks_crossed": int(ticks_crossed),
                        "gas_est": int(gas_est),
                    }
            except Exception as exc:  # noqa: BLE001
                last_exc = str(exc)

        if not best:
            raise HTTPException(
                400,
                {
                    "error": "NO_ROUTE",
                    "msg": "No route available (all fee tiers reverted)",
                    "pool_used": pool_uni,
                    "pool_fee": pool_fee,
                    "pool_token0": pool_t0,
                    "pool_token1": pool_t1,
                    "pool_symbols": [t0_sym, t1_sym],
                    "req_token_in": token_in,
                    "req_token_out": token_out,
                    "last_exception": last_exc,
                    "hints": [
                        "Check if USDC is the native one or bridged.",
                        "Confirm that pair and fee (pool_fee) match the informed pool.",
                        "Ensure amount_in is not too small (amount_out=0).",
                        "Confirm UNI_V3_QUOTER is correct for the current chain.",
                    ],
                },
            )

        gas_price_wei = int(ad_uni.w3.eth.gas_price)
        gas_eth = float(
            (Decimal(best["gas_est"]) * Decimal(gas_price_wei)) / Decimal(10**18)
        )

        dec0, dec1 = int(meta_uni["dec0"]), int(meta_uni["dec1"])
        sqrtP, _ = ad_uni.slot0()
        p_t1_t0 = sqrtPriceX96_to_price_t1_per_t0(sqrtP, dec0, dec1)

        def _is_usdc(sym: str) -> bool:
            return sym.upper() in USD_SYMBOLS

        def _is_eth(sym: str) -> bool:
            return sym.upper() in {"WETH", "ETH"}

        usdc_per_eth: Optional[float] = None
        if _is_usdc(t1_sym) and _is_eth(t0_sym):
            usdc_per_eth = p_t1_t0
        elif _is_usdc(t0_sym) and _is_eth(t1_sym):
            usdc_per_eth = 0.0 if p_t1_t0 == 0 else 1.0 / float(p_t1_t0)

        gas_usd = (gas_eth * float(usdc_per_eth)) if usdc_per_eth else None

        amount_out_human = float(best["amount_out_raw"]) / (10**dec_out)
        value_at_sqrt_after_usd = _value_usd(
            0,
            amount_out_human,
            p_t1_t0,
            1 / p_t1_t0 if p_t1_t0 else 0.0,
            t0_sym,
            t1_sym,
            pool_t0,
            pool_t1,
        )

        return {
            "best_fee": int(best["fee"]),
            "best_tick_spacing": int(best["fee"]),
            "amount_in_raw": int(amount_in_raw),
            "amount_out_raw": int(best["amount_out_raw"]),
            "amount_in": float(req.amount_in),
            "amount_out": float(amount_out_human),
            "sqrtPriceX96_after": int(best["sqrt_after"]),
            "initialized_ticks_crossed": int(best["ticks_crossed"]),
            "gas_estimate": int(best["gas_est"]),
            "gas_price_wei": int(gas_price_wei),
            "gas_price_gwei": float(Decimal(gas_price_wei) / Decimal(10**9)),
            "gas_eth": float(gas_eth),
            "gas_usd": float(gas_usd) if gas_usd is not None else None,
            "value_at_sqrt_after_usd": float(value_at_sqrt_after_usd),
            "pool_used": pool_uni,
            "pool_symbols": [t0_sym, t1_sym],
        }

    def uniswap_swap_exact_in(self, alias: str, req: SwapExactInRequest) -> dict[str, Any]:
        """
        Execute an exact-in swap from a vault using Uniswap v3.

        The high-level flow is:
          1) Resolve vault (regardless of DEX) and check configuration.
          2) Initialize state tracking for the vault, if needed.
          3) Build adapters for the vault and the Uniswap pool to be used.
          4) Compute amount_in_raw based on token or USD (when token_in is
             WETH/ETH or USDC), using the Uniswap pool price.
          5) Validate vault balance for token_in.
          6) Use the quote endpoint to obtain best_fee and amount_out_raw.
          7) Apply slippage (slippage_bps) to compute min_out_raw.
          8) Build the vault contract call and send the transaction via TxService,
             enforcing a gas cost upper bound (max_budget_usd).
          9) Record pre/post snapshots and execution history in the state repo.
         10) Optionally convert gauge rewards to USDC and register them.

        Args:
            alias: Human-friendly alias of the vault.
            req: SwapExactInRequest with token addresses, amount_in or
                amount_in_usd, optional fee, slippage, pool_override and
                max_budget_usd.

        Returns:
            A dictionary containing:
                - tx hash
                - tick_spacing_used (alias for fee tier)
                - resolved_amount_mode ("token" or "usd")
                - amount_in_raw / quoted_out_raw / min_out_raw
                - gas usage and gas in ETH/USD
                - hints about gas budget checking
                - before/after snapshots
                - pool_used and value_at_sqrt_after_usd
                - optional rewards_added snapshot (if convert_gauge_to_usdc)

        Raises:
            HTTPException:
                - 404 for unknown alias.
                - 500 if UNI_V3_ROUTER/UNI_V3_QUOTER are not configured.
                - 400 for invalid amounts, insufficient balance or budget
                  exceeded.
                - 502 when the on-chain transaction reverts.
        """
        dex_for_swap = "uniswap"

        vault_dex, v = self._vault_repo.get_vault_any(alias)
        if not v:
            raise HTTPException(404, "Unknown alias (not found in uniswap or aerodrome)")

        s = get_settings()
        if not s.UNI_V3_ROUTER or not s.UNI_V3_QUOTER:
            raise HTTPException(500, "UNI_V3_ROUTER/UNI_V3_QUOTER not configured")

        self._state_repo.ensure_state_initialized(vault_dex, alias, vault_address=v["address"])

        ad_vault = get_adapter_for(
            vault_dex, v["pool"], v.get("nfpm"), v["address"], v.get("rpc_url"), v.get("gauge")
        )
        pool_uni = resolve_pool_from_vault(v, req.pool_override)
        ad_uni = get_adapter_for("uniswap", pool_uni, None, v["address"], v.get("rpc_url"))

        try:
            before = snapshot_status(ad_vault, vault_dex, alias)
        except Exception:  # noqa: BLE001
            before = {"warning": "status_unavailable_for_this_dex"}

        dec_in = int(ad_vault.erc20(req.token_in).functions.decimals().call())
        dec_out = int(ad_vault.erc20(req.token_out).functions.decimals().call())

        def _is_usdc(sym: str) -> bool:
            return sym.upper() in USD_SYMBOLS

        def _is_eth(sym: str) -> bool:
            return sym.upper() in {"WETH", "ETH"}

        amount_in_raw: Optional[int] = None
        resolved_mode: Optional[str] = None

        if req.amount_in is not None:
            amount_in_raw = int(float(req.amount_in) * (10**dec_in))
            resolved_mode = "token"
        elif req.amount_in_usd is not None:
            meta_uni = ad_uni.pool_meta()
            sym0, sym1 = meta_uni["sym0"], meta_uni["sym1"]
            dec0, dec1 = int(meta_uni["dec0"]), int(meta_uni["dec1"])
            sqrtP, _ = ad_uni.slot0()
            p_t1_t0 = sqrtPriceX96_to_price_t1_per_t0(sqrtP, dec0, dec1)

            usdc_per_eth = None
            if _is_usdc(sym1) and _is_eth(sym0):
                usdc_per_eth = p_t1_t0
            elif _is_usdc(sym0) and _is_eth(sym1):
                usdc_per_eth = 0.0 if p_t1_t0 == 0 else 1.0 / float(p_t1_t0)

            in_sym = ad_vault.erc20(req.token_in).functions.symbol().call()
            if _is_eth(in_sym):
                if not usdc_per_eth:
                    raise HTTPException(
                        400,
                        "Could not derive USDC/ETH price from Uniswap pool.",
                    )
                amount_in_token = float(req.amount_in_usd) / float(usdc_per_eth)
                amount_in_raw = int(amount_in_token * (10**dec_in))
                resolved_mode = "usd"
            elif _is_usdc(in_sym):
                amount_in_raw = int(float(req.amount_in_usd) * (10**dec_in))
                resolved_mode = "usd"
            else:
                raise HTTPException(
                    400,
                    "amount_in_usd is only supported when token_in is WETH/ETH or USDC.",
                )
        else:
            raise HTTPException(400, "You must provide amount_in (token) or amount_in_usd.")

        if not amount_in_raw or amount_in_raw <= 0:
            raise HTTPException(400, "amount_in must be > 0")

        bal_in = int(
            ad_vault.erc20(req.token_in).functions.balanceOf(v["address"]).call()
        )
        if bal_in < amount_in_raw:
            raise HTTPException(
                400, f"insufficient vault balance: have {bal_in}, need {amount_in_raw}"
            )

        fee = int(req.fee) if req.fee is not None else None
        quote = self.uniswap_swap_quote(
            alias,
            SwapQuoteRequest(
                alias=alias,
                token_in=req.token_in,
                token_out=req.token_out,
                amount_in=(
                    float(req.amount_in)
                    if resolved_mode == "token"
                    else float(amount_in_raw) / (10**dec_in)
                ),
                fee=fee,
                sqrt_price_limit_x96=req.sqrt_price_limit_x96,
                pool_override=req.pool_override,
            ),
        )
        fee_used = int(quote["best_fee"])
        amount_out_raw = int(quote["amount_out_raw"])
        if amount_out_raw <= 0:
            raise HTTPException(400, "quoter returned 0")

        bps = max(0, int(req.slippage_bps))
        min_out_raw = amount_out_raw * (10_000 - bps) // 10_000

        fn = ad_uni.fn_vault_swap_exact_in(
            router=get_settings().UNI_V3_ROUTER,
            token_in=req.token_in,
            token_out=req.token_out,
            fee=fee_used,
            amount_in_raw=amount_in_raw,
            min_out_raw=min_out_raw,
            sqrt_price_limit_x96=int(req.sqrt_price_limit_x96 or 0),
        )

        eth_usd_hint = estimate_eth_usd_from_pool(ad_uni)
        txs = TxService(v.get("rpc_url"))

        try:
            send_res = txs.send(
                fn,
                wait=True,
                gas_strategy="buffered",
                max_gas_usd=req.max_budget_usd,
                eth_usd_hint=eth_usd_hint,
            )
        except TransactionBudgetExceededError as exc:
            payload = {
                "tx_hash": None,
                "broadcasted": False,
                "status": None,
                "error_type": "BUDGET_EXCEEDED",
                "error_msg": "Gas cost upper bound is above allowed max_gas_usd",
                "budget_info": {
                    "usd_budget": exc.usd_budget,
                    "usd_estimated_upper_bound": exc.usd_estimated,
                    "eth_usd_hint": exc.eth_usd,
                    "gas_price_wei": exc.gas_price_wei,
                    "est_gas_limit": exc.est_gas_limit,
                },
            }
            self._state_repo.append_history(
                dex_for_swap,
                alias,
                "exec_history",
                {
                    "ts": datetime.utcnow().isoformat(),
                    "mode": "swap_exact_in_failed_budget_uniswap",
                    "payload": payload,
                },
            )
            raise HTTPException(status_code=400, detail=payload) from exc

        except TransactionRevertedError as exc:
            rcpt = exc.receipt or {}
            gas_used = int(rcpt.get("gasUsed") or 0)
            eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

            gas_eth = gas_usd = None
            if gas_used and eff_price_wei and eth_usd_hint:
                gas_eth = float(
                    (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
                )
                gas_usd = gas_eth * float(eth_usd_hint)

            payload = {
                "tx_hash": exc.tx_hash,
                "broadcasted": True,
                "status": 0,
                "error_type": "ONCHAIN_REVERT",
                "error_msg": exc.msg,
                "receipt": rcpt,
                "gas_used": gas_used,
                "effective_gas_price_wei": eff_price_wei,
                "gas_eth": gas_eth,
                "gas_usd": gas_usd,
            }
            self._state_repo.append_history(
                dex_for_swap,
                alias,
                "exec_history",
                {
                    "ts": datetime.utcnow().isoformat(),
                    "mode": "swap_exact_in_failed_revert_uniswap",
                    "payload": payload,
                },
            )
            raise HTTPException(status_code=502, detail=payload) from exc

        rcpt = send_res["receipt"] or {}
        gas_used = int(rcpt.get("gasUsed") or 0)
        eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

        gas_eth = gas_usd = None
        if gas_used and eff_price_wei and eth_usd_hint:
            gas_eth = float(
                (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
            )
            gas_usd = gas_eth * float(eth_usd_hint)

        try:
            after = snapshot_status(ad_vault, vault_dex, alias)
        except Exception:  # noqa: BLE001
            after = {"warning": "status_unavailable_for_this_dex"}

        self._state_repo.append_history(
            dex_for_swap,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "swap_exact_in_uniswap",
                "token_in": req.token_in,
                "token_out": req.token_out,
                "resolved_amount_mode": resolved_mode,
                "amount_in_raw": amount_in_raw,
                "min_out_raw": min_out_raw,
                "fee_used": fee_used,
                "slippage_bps": bps,
                "tx": send_res["tx_hash"],
                "gas_used": gas_used,
                "effective_gas_price_wei": eff_price_wei,
                "gas_eth": gas_eth,
                "gas_usd": gas_usd,
                "gas_budget_check": send_res.get("gas_budget_check"),
                "send_res": send_res,
                "value_at_sqrt_after_usd": quote["value_at_sqrt_after_usd"],
                "pool_used": pool_uni,
            },
        )

        rewards_added = None
        if req.convert_gauge_to_usdc:
            try:
                usdc_raw = int(amount_out_raw)
                usdc_human = float(usdc_raw) / (10**dec_out)

                try:
                    in_sym = ad_vault.erc20(req.token_in).functions.symbol().call()
                    out_sym = ad_vault.erc20(req.token_out).functions.symbol().call()
                except Exception:  # noqa: BLE001
                    in_sym, out_sym = "IN", "OUT"

                self._state_repo.add_rewards_usdc_snapshot(
                    dex=vault_dex,
                    alias=alias,
                    usdc_raw=usdc_raw,
                    usdc_human=usdc_human,
                    meta={
                        "tx_hash": send_res["tx_hash"],
                        "token_in": req.token_in,
                        "token_out": req.token_out,
                        "token_in_symbol": in_sym,
                        "token_out_symbol": out_sym,
                        "pool_used": pool_uni,
                        "fee_used": fee_used,
                        "mode": "swap_reward_to_usdc_uniswap",
                    },
                )
                rewards_added = {"usdc_raw": usdc_raw, "usdc_human": usdc_human}
            except Exception as exc:  # noqa: BLE001
                import logging

                logging.warning("Failed to add rewards_usdc_snapshot (uniswap): %s", exc)

        return {
            "tx": send_res["tx_hash"],
            "tick_spacing_used": fee_used,
            "resolved_amount_mode": resolved_mode,
            "amount_in_raw": amount_in_raw,
            "quoted_out_raw": amount_out_raw,
            "min_out_raw": min_out_raw,
            "value_at_sqrt_after_usd": quote["value_at_sqrt_after_usd"],
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
            "budget": send_res.get("gas_budget_check"),
            "before": before,
            "after": after,
            "send_res": send_res,
            "pool_used": pool_uni,
            "rewards_added": rewards_added,
        }

    # -------------------------------------------------------------------------
    # AERODROME
    # -------------------------------------------------------------------------

    def aerodrome_swap_quote(self, alias: str, req: SwapQuoteRequest) -> dict[str, Any]:
        """
        Quote an exact-in swap using an Aerodrome pool for a given vault.

        The semantics mirror the Uniswap quote but use Aerodrome-specific
        tickSpacing candidates and AERO_QUOTER.

        Args:
            alias: Vault alias.
            req: SwapQuoteRequest containing token_in, token_out and amount_in
                in human units, plus optional tickSpacing override, sqrt price
                limit and pool override.

        Returns:
            A structured dictionary with the best tick_spacing, raw/human
            amounts, gas estimates, price impact proxy and pool metadata.

        Raises:
            HTTPException:
                - 404 if the alias is unknown.
                - 500 if AERO_QUOTER is missing.
                - 400 if amount_in <= 0 or all tickSpacings revert.
        """
        dex_for_quote = "aerodrome"

        vault_dex, v = self._vault_repo.get_vault_any(alias)
        if not v:
            raise HTTPException(404, "Unknown alias (not found in uniswap or aerodrome)")

        s = get_settings()
        if not s.AERO_QUOTER:
            raise HTTPException(500, "AERO_QUOTER not configured")

        ad_vault = get_adapter_for(
            vault_dex, v["pool"], v.get("nfpm"), v["address"], v.get("rpc_url"), v.get("gauge")
        )

        pool_aero = resolve_pool_from_vault(v, req.pool_override)
        ad_aero = get_adapter_for(dex_for_quote, pool_aero, None, v["address"], v.get("rpc_url"))
        quoter = ad_aero.aerodrome_quoter(s.AERO_QUOTER)

        token_in = Web3.to_checksum_address(req.token_in)
        token_out = Web3.to_checksum_address(req.token_out)

        dec_in = int(ad_vault.erc20(token_in).functions.decimals().call())
        dec_out = int(ad_vault.erc20(token_out).functions.decimals().call())

        amount_in_raw = int(float(req.amount_in) * (10**dec_in))
        if amount_in_raw <= 0:
            raise HTTPException(400, "amount_in must be > 0")

        candidates = [int(req.fee)] if req.fee is not None else tick_spacing_candidates(ad_aero)

        best: Optional[dict[str, Any]] = None
        for ts in candidates:
            params = {
                "tokenIn": token_in,
                "tokenOut": token_out,
                "amountIn": int(amount_in_raw),
                "tickSpacing": int(ts),
                "sqrtPriceLimitX96": int(req.sqrt_price_limit_x96 or 0),
            }
            try:
                amount_out_raw, sqrt_after, ticks_crossed, gas_est = (
                    quoter.functions.quoteExactInputSingle(params).call()
                )
                if int(amount_out_raw) > 0 and (
                    not best or int(amount_out_raw) > best["amount_out_raw"]
                ):
                    best = {
                        "tick_spacing": int(ts),
                        "amount_out_raw": int(amount_out_raw),
                        "sqrt_after": int(sqrt_after),
                        "ticks_crossed": int(ticks_crossed),
                        "gas_est": int(gas_est),
                    }
            except Exception:  # noqa: BLE001
                continue

        if not best:
            raise HTTPException(400, "No route available (all tickSpacings reverted)")

        gas_price_wei = int(ad_aero.w3.eth.gas_price)
        gas_eth = float(
            (Decimal(best["gas_est"]) * Decimal(gas_price_wei)) / Decimal(10**18)
        )

        meta = ad_aero.pool_meta()
        dec0, dec1 = int(meta["dec0"]), int(meta["dec1"])
        sym0, sym1 = str(meta["sym0"]).upper(), str(meta["sym1"]).upper()
        t0 = Web3.to_checksum_address(meta["token0"])
        t1 = Web3.to_checksum_address(meta["token1"])

        sqrtP, _ = ad_aero.slot0()
        p_t1_t0 = sqrtPriceX96_to_price_t1_per_t0(sqrtP, dec0, dec1)

        def _is_usdc(sym: str) -> bool:
            return sym in USD_SYMBOLS

        def _is_eth(sym: str) -> bool:
            return sym in {"WETH", "ETH"}

        usdc_per_eth = None
        if _is_usdc(sym1) and _is_eth(sym0):
            usdc_per_eth = p_t1_t0
        elif _is_usdc(sym0) and _is_eth(sym1):
            usdc_per_eth = 0 if p_t1_t0 == 0 else 1 / p_t1_t0

        gas_usd = (gas_eth * float(usdc_per_eth)) if usdc_per_eth else None

        amount_out_human = float(best["amount_out_raw"]) / (10**dec_out)
        value_at_sqrt_after_usd = _value_usd(
            0,
            amount_out_human,
            p_t1_t0,
            1 / p_t1_t0 if p_t1_t0 else 0.0,
            sym0,
            sym1,
            t0,
            t1,
        )

        return {
            "best_tick_spacing": int(best["tick_spacing"]),
            "amount_in_raw": int(amount_in_raw),
            "amount_out_raw": int(best["amount_out_raw"]),
            "amount_in": float(req.amount_in),
            "amount_out": float(amount_out_human),
            "sqrtPriceX96_after": int(best["sqrt_after"]),
            "initialized_ticks_crossed": int(best["ticks_crossed"]),
            "gas_estimate": int(best["gas_est"]),
            "gas_price_wei": int(gas_price_wei),
            "gas_price_gwei": float(Decimal(gas_price_wei) / Decimal(10**9)),
            "gas_eth": float(gas_eth),
            "gas_usd": float(gas_usd) if gas_usd else None,
            "value_at_sqrt_after_usd": float(value_at_sqrt_after_usd),
        }

    def aerodrome_swap_exact_in(self, alias: str, req: SwapExactInRequest) -> dict[str, Any]:
        """
        Execute an exact-in swap for a vault using an Aerodrome pool.

        The flow is analogous to `uniswap_swap_exact_in` but uses Aerodrome
        router/quoters and the `fn_vault_swap_exact_in_aero` function on the
        adapter.

        Args:
            alias: Vault alias.
            req: SwapExactInRequest with token_in/token_out, amount_in or
                amount_in_usd, slippage, fee override, pool override and max
                gas budget.

        Returns:
            Result structure with transaction hash, amount details, gas usage,
            before/after snapshots and pool metadata.

        Raises:
            HTTPException on invalid config, insufficient balance, budget
            exceeded or on-chain revert.
        """
        dex_for_swap = "aerodrome"

        vault_dex, v = self._vault_repo.get_vault_any(alias)
        if not v:
            raise HTTPException(404, "Unknown alias (not found in uniswap or aerodrome)")

        s = get_settings()
        if not s.AERO_ROUTER or not s.AERO_QUOTER:
            raise HTTPException(500, "AERO_ROUTER/AERO_QUOTER not configured")

        self._state_repo.ensure_state_initialized(dex_for_swap, alias, vault_address=v["address"])

        ad_vault = get_adapter_for(
            vault_dex, v["pool"], v.get("nfpm"), v["address"], v.get("rpc_url"), v.get("gauge")
        )
        pool_aero = resolve_pool_from_vault(v, req.pool_override)
        ad_aero = get_adapter_for(dex_for_swap, pool_aero, None, v["address"], v.get("rpc_url"))

        try:
            before = snapshot_status(ad_vault, vault_dex, alias)
        except Exception:  # noqa: BLE001
            before = {"warning": "status_unavailable_for_this_dex"}

        dec_in = int(ad_vault.erc20(req.token_in).functions.decimals().call())
        dec_out = int(ad_vault.erc20(req.token_out).functions.decimals().call())

        def _is_usdc(sym: str) -> bool:
            return sym.upper() in USD_SYMBOLS

        def _is_eth(sym: str) -> bool:
            return sym.upper() in {"WETH", "ETH"}

        amount_in_raw: Optional[int] = None
        resolved_mode: Optional[str] = None

        if req.amount_in is not None:
            amount_in_raw = int(float(req.amount_in) * (10**dec_in))
            resolved_mode = "token"
        elif req.amount_in_usd is not None:
            meta = ad_aero.pool_meta()
            sym0, sym1 = meta["sym0"], meta["sym1"]
            dec0, dec1 = int(meta["dec0"]), int(meta["dec1"])
            sqrtP, _ = ad_aero.slot0()
            p_t1_t0 = sqrtPriceX96_to_price_t1_per_t0(sqrtP, dec0, dec1)

            usdc_per_eth = None
            if _is_usdc(sym1) and _is_eth(sym0):
                usdc_per_eth = p_t1_t0
            elif _is_usdc(sym0) and _is_eth(sym1):
                usdc_per_eth = 0.0 if p_t1_t0 == 0 else 1.0 / float(p_t1_t0)

            in_sym = ad_vault.erc20(req.token_in).functions.symbol().call()
            if _is_eth(in_sym):
                if not usdc_per_eth:
                    raise HTTPException(
                        400,
                        "Could not derive USDC/ETH price from Aerodrome pool.",
                    )
                amount_in_token = float(req.amount_in_usd) / float(usdc_per_eth)
                amount_in_raw = int(amount_in_token * (10**dec_in))
                resolved_mode = "usd"
            elif _is_usdc(in_sym):
                amount_in_raw = int(float(req.amount_in_usd) * (10**dec_in))
                resolved_mode = "usd"
            else:
                raise HTTPException(
                    400,
                    "amount_in_usd is only supported when token_in is WETH/ETH or USDC.",
                )
        else:
            raise HTTPException(400, "You must provide amount_in (token) or amount_in_usd.")

        if not amount_in_raw or amount_in_raw <= 0:
            raise HTTPException(400, "amount_in must be > 0")

        bal_in = int(
            ad_vault.erc20(req.token_in).functions.balanceOf(v["address"]).call()
        )
        if bal_in < amount_in_raw:
            raise HTTPException(
                400, f"insufficient vault balance: have {bal_in}, need {amount_in_raw}"
            )

        fee = int(req.fee) if req.fee is not None else None
        quote = self.aerodrome_swap_quote(
            alias,
            SwapQuoteRequest(
                alias=alias,
                token_in=req.token_in,
                token_out=req.token_out,
                amount_in=(
                    float(req.amount_in)
                    if resolved_mode == "token"
                    else float(amount_in_raw) / (10**dec_in)
                ),
                fee=fee,
                sqrt_price_limit_x96=req.sqrt_price_limit_x96,
                pool_override=pool_aero,
            ),
        )
        ts_used = int(quote["best_tick_spacing"])
        amount_out_raw = int(quote["amount_out_raw"])
        if amount_out_raw <= 0:
            raise HTTPException(400, "quoter returned 0")

        bps = max(0, int(req.slippage_bps))
        min_out_raw = amount_out_raw * (10_000 - bps) // 10_000

        fn = ad_aero.fn_vault_swap_exact_in_aero(
            router=s.AERO_ROUTER,
            token_in=req.token_in,
            token_out=req.token_out,
            tick_spacing=ts_used,
            amount_in_raw=amount_in_raw,
            min_out_raw=min_out_raw,
            sqrt_price_limit_x96=int(req.sqrt_price_limit_x96 or 0),
        )

        eth_usd_hint = estimate_eth_usd_from_pool(ad_aero)
        txs = TxService(v.get("rpc_url"))

        try:
            send_res = txs.send(
                fn,
                wait=True,
                gas_strategy="buffered",
                max_gas_usd=req.max_budget_usd,
                eth_usd_hint=eth_usd_hint,
            )
        except TransactionBudgetExceededError as exc:
            payload = {
                "tx_hash": None,
                "broadcasted": False,
                "status": None,
                "error_type": "BUDGET_EXCEEDED",
                "error_msg": "Gas cost upper bound is above allowed max_gas_usd",
                "budget_info": {
                    "usd_budget": exc.usd_budget,
                    "usd_estimated_upper_bound": exc.usd_estimated,
                    "eth_usd_hint": exc.eth_usd,
                    "gas_price_wei": exc.gas_price_wei,
                    "est_gas_limit": exc.est_gas_limit,
                },
            }
            self._state_repo.append_history(
                dex_for_swap,
                alias,
                "exec_history",
                {
                    "ts": datetime.utcnow().isoformat(),
                    "mode": "swap_exact_in_failed_budget_aerodrome",
                    "payload": payload,
                },
            )
            raise HTTPException(status_code=400, detail=payload) from exc

        except TransactionRevertedError as exc:
            rcpt = exc.receipt or {}
            gas_used = int(rcpt.get("gasUsed") or 0)
            eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

            gas_eth = gas_usd = None
            if gas_used and eff_price_wei and eth_usd_hint:
                gas_eth = float(
                    (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
                )
                gas_usd = gas_eth * float(eth_usd_hint)

            payload = {
                "tx_hash": exc.tx_hash,
                "broadcasted": True,
                "status": 0,
                "error_type": "ONCHAIN_REVERT",
                "error_msg": exc.msg,
                "receipt": rcpt,
                "gas_used": gas_used,
                "effective_gas_price_wei": eff_price_wei,
                "gas_eth": gas_eth,
                "gas_usd": gas_usd,
            }
            self._state_repo.append_history(
                dex_for_swap,
                alias,
                "exec_history",
                {
                    "ts": datetime.utcnow().isoformat(),
                    "mode": "swap_exact_in_failed_revert_aerodrome",
                    "payload": payload,
                },
            )
            raise HTTPException(status_code=502, detail=payload) from exc

        rcpt = send_res["receipt"] or {}
        gas_used = int(rcpt.get("gasUsed") or 0)
        eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)

        gas_eth = gas_usd = None
        if gas_used and eff_price_wei and eth_usd_hint:
            gas_eth = float(
                (Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18)
            )
            gas_usd = gas_eth * float(eth_usd_hint)

        try:
            after = snapshot_status(ad_vault, vault_dex, alias)
        except Exception:  # noqa: BLE001
            after = {"warning": "status_unavailable_for_this_dex"}

        self._state_repo.append_history(
            dex_for_swap,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "swap_exact_in_aerodrome",
                "token_in": req.token_in,
                "token_out": req.token_out,
                "resolved_amount_mode": resolved_mode,
                "amount_in_raw": amount_in_raw,
                "min_out_raw": min_out_raw,
                "tick_spacing_used": ts_used,
                "slippage_bps": bps,
                "tx": send_res["tx_hash"],
                "gas_used": gas_used,
                "effective_gas_price_wei": eff_price_wei,
                "gas_eth": gas_eth,
                "gas_usd": gas_usd,
                "gas_budget_check": send_res.get("gas_budget_check"),
                "send_res": send_res,
                "value_at_sqrt_after_usd": quote["value_at_sqrt_after_usd"],
                "pool_used": pool_aero,
            },
        )

        return {
            "tx": send_res["tx_hash"],
            "tick_spacing_used": ts_used,
            "resolved_amount_mode": resolved_mode,
            "amount_in_raw": amount_in_raw,
            "quoted_out_raw": amount_out_raw,
            "min_out_raw": min_out_raw,
            "value_at_sqrt_after_usd": quote["value_at_sqrt_after_usd"],
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
            "budget": send_res.get("gas_budget_check"),
            "before": before,
            "after": after,
            "send_res": send_res,
            "pool_used": pool_aero,
        }

    # -------------------------------------------------------------------------
    # PANCAKE v3
    # -------------------------------------------------------------------------

    def pancake_swap_quote(self, alias: str, req: SwapQuoteRequest) -> dict[str, Any]:
        """
        Quote an exact-in swap for a vault using Pancake v3.

        Args:
            alias: Vault alias.
            req: SwapQuoteRequest with token_in, token_out and amount_in
                in human units, plus optional fee override and pool_override.

        Returns:
            Quote containing best_fee, raw/human amounts, gas estimates,
            pool metadata and a USD estimate of the resulting value.

        Raises:
            HTTPException on unknown alias, missing PANCAKE_V3_QUOTER,
            invalid amount_in or missing route.
        """
        dex_for_quote = "pancake"

        vault_dex, v = self._vault_repo.get_vault_any(alias)
        if not v:
            raise HTTPException(404, "Unknown alias")

        s = get_settings()
        if not getattr(s, "PANCAKE_V3_QUOTER", None):
            raise HTTPException(500, "PANCAKE_V3_QUOTER not configured")

        ad_vault = get_adapter_for(
            vault_dex, v["pool"], v.get("nfpm"), v["address"], v.get("rpc_url"), v.get("gauge")
        )

        pool_addr = resolve_pool_from_vault(v, req.pool_override)
        ad_pc = get_adapter_for(dex_for_quote, pool_addr, None, v["address"], v.get("rpc_url"))
        quoter = ad_pc.quoter(s.PANCAKE_V3_QUOTER)

        meta = ad_pc.pool_meta()
        pool_t0 = Web3.to_checksum_address(meta["token0"])
        pool_t1 = Web3.to_checksum_address(meta["token1"])
        fee = int(ad_pc.pool_contract().functions.fee().call())
        t0_sym, t1_sym = meta["sym0"], meta["sym1"]

        token_in = Web3.to_checksum_address(req.token_in)
        token_out = Web3.to_checksum_address(req.token_out)
        if {token_in, token_out} != {pool_t0, pool_t1}:
            raise HTTPException(
                400,
                {
                    "error": "TOKENS_NOT_IN_POOL",
                    "pool_used": pool_addr,
                    "pool_token0": pool_t0,
                    "pool_token1": pool_t1,
                    "pool_symbols": [t0_sym, t1_sym],
                    "req_token_in": token_in,
                    "req_token_out": token_out,
                },
            )

        dec_in = int(ad_vault.erc20(token_in).functions.decimals().call())
        dec_out = int(ad_vault.erc20(token_out).functions.decimals().call())
        amount_in_raw = int(float(req.amount_in) * (10**dec_in))
        if amount_in_raw <= 0:
            raise HTTPException(400, "amount_in must be > 0")

        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "amountIn": int(amount_in_raw),
            "fee": int(fee),
            "sqrtPriceLimitX96": int(req.sqrt_price_limit_x96 or 0),
        }

        try:
            amount_out_raw, sqrt_after, ticks_crossed, gas_est = (
                quoter.functions.quoteExactInputSingle(params).call()
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                400, {"error": "NO_ROUTE", "details": str(exc)}
            ) from exc

        gas_price_wei = int(ad_pc.w3.eth.gas_price)
        gas_eth = float((Decimal(gas_est) * Decimal(gas_price_wei)) / Decimal(10**18))

        dec0, dec1 = int(meta["dec0"]), int(meta["dec1"])
        sqrtP, _ = ad_pc.slot0()
        p_t1_t0 = sqrtPriceX96_to_price_t1_per_t0(sqrtP, dec0, dec1)

        def _is_usd(sym: str) -> bool:
            return str(sym).upper() in USD_SYMBOLS

        def _is_eth(sym: str) -> bool:
            return str(sym).upper() in {"WETH", "ETH"}

        usdc_per_eth = None
        if _is_usd(meta["sym1"]) and _is_eth(meta["sym0"]):
            usdc_per_eth = p_t1_t0
        elif _is_usd(meta["sym0"]) and _is_eth(meta["sym1"]):
            usdc_per_eth = 0 if p_t1_t0 == 0 else 1 / p_t1_t0

        gas_usd = (gas_eth * float(usdc_per_eth)) if usdc_per_eth else None

        amount_out_human = float(amount_out_raw) / (10**dec_out)
        value_at_sqrt_after_usd = _value_usd(
            0,
            amount_out_human,
            p_t1_t0,
            1 / p_t1_t0 if p_t1_t0 else 0.0,
            meta["sym0"],
            meta["sym1"],
            pool_t0,
            pool_t1,
        )

        return {
            "best_fee": int(fee),
            "best_tick_spacing": int(fee),
            "amount_in_raw": int(amount_in_raw),
            "amount_out_raw": int(amount_out_raw),
            "amount_in": float(req.amount_in),
            "amount_out": float(amount_out_human),
            "sqrtPriceX96_after": int(sqrt_after),
            "initialized_ticks_crossed": int(ticks_crossed),
            "gas_estimate": int(gas_est),
            "gas_price_wei": int(gas_price_wei),
            "gas_price_gwei": float(Decimal(gas_price_wei) / Decimal(10**9)),
            "gas_eth": float(gas_eth),
            "gas_usd": float(gas_usd) if gas_usd else None,
            "value_at_sqrt_after_usd": float(value_at_sqrt_after_usd),
            "pool_used": pool_addr,
            "pool_symbols": [t0_sym, t1_sym],
        }

    def pancake_swap_exact_in(self, alias: str, req: SwapExactInRequest) -> dict[str, Any]:
        """
        Execute an exact-in swap from a Pancake v3 vault.

        This mirrors the Aerodrome implementation but uses Pancake v3 router
        and quoter, plus the `fn_vault_swap_exact_in_pancake` helper on the
        adapter.

        Args:
            alias: Vault alias (must resolve to a Pancake vault or a vault that
                has a valid Pancake pool configured).
            req: SwapExactInRequest with token_in/token_out, amount_in or
                amount_in_usd, slippage, fee override, pool override and max
                gas budget.

        Returns:
            A dictionary containing transaction hash, raw/human amounts,
            gas usage, snapshot information and pool metadata.

        Raises:
            HTTPException on unknown alias, invalid settings, invalid amounts,
            insufficient vault balance, budget exceeded or on-chain revert.
        """
        dex_for_swap = "pancake"

        vault_dex, v = self._vault_repo.get_vault_any(alias)
        if not v:
            raise HTTPException(404, "Unknown alias")

        s = get_settings()
        if not getattr(s, "PANCAKE_V3_ROUTER", None) or not getattr(
            s, "PANCAKE_V3_QUOTER", None
        ):
            raise HTTPException(500, "PANCAKE_V3_ROUTER/PANCAKE_V3_QUOTER not configured")

        self._state_repo.ensure_state_initialized(dex_for_swap, alias, vault_address=v["address"])

        ad_vault = get_adapter_for(
            vault_dex, v["pool"], v.get("nfpm"), v["address"], v.get("rpc_url"), v.get("gauge")
        )
        pool_addr = resolve_pool_from_vault(v, req.pool_override)
        ad_pc = get_adapter_for(dex_for_swap, pool_addr, None, v["address"], v.get("rpc_url"))

        try:
            before = snapshot_status(ad_vault, vault_dex, alias)
        except Exception:  # noqa: BLE001
            before = {"warning": "status_unavailable_for_this_dex"}

        dec_in = int(ad_vault.erc20(req.token_in).functions.decimals().call())
        dec_out = int(ad_vault.erc20(req.token_out).functions.decimals().call())

        def _is_usdc(sym: str) -> bool:
            return sym.upper() in USD_SYMBOLS

        def _is_eth(sym: str) -> bool:
            return sym.upper() in {"WETH", "ETH"}

        amount_in_raw: int
        resolved_mode: str

        meta_swap = ad_pc.pool_meta()
        sym0_s, sym1_s = meta_swap["sym0"], meta_swap["sym1"]
        dec0_s, dec1_s = int(meta_swap["dec0"]), int(meta_swap["dec1"])
        sqrtP_s, _ = ad_pc.slot0()
        p_t1_t0_swap = sqrtPriceX96_to_price_t1_per_t0(sqrtP_s, dec0_s, dec1_s)

        if req.amount_in is not None:
            amount_in_raw = int(float(req.amount_in) * (10**dec_in))
            resolved_mode = "token"
        elif req.amount_in_usd is not None:
            usdc_per_eth = None
            if _is_usdc(sym1_s) and _is_eth(sym0_s):
                usdc_per_eth = p_t1_t0_swap
            elif _is_usdc(sym0_s) and _is_eth(sym1_s):
                usdc_per_eth = 0.0 if p_t1_t0_swap == 0 else 1.0 / float(p_t1_t0_swap)

            in_sym = ad_vault.erc20(req.token_in).functions.symbol().call()
            if _is_eth(in_sym):
                if not usdc_per_eth:
                    raise HTTPException(
                        400,
                        "Could not derive USDC/ETH price from Pancake pool.",
                    )
                amount_in_token = float(req.amount_in_usd) / float(usdc_per_eth)
                amount_in_raw = int(amount_in_token * (10**dec_in))
                resolved_mode = "usd"
            elif _is_usdc(in_sym):
                amount_in_raw = int(float(req.amount_in_usd) * (10**dec_in))
                resolved_mode = "usd"
            else:
                raise HTTPException(
                    400,
                    "amount_in_usd is only supported when token_in is WETH/ETH or USDC.",
                )
        else:
            raise HTTPException(400, "You must provide amount_in (token) or amount_in_usd.")

        if amount_in_raw <= 0:
            raise HTTPException(400, "amount_in must be > 0")

        bal_in = int(
            ad_vault.erc20(req.token_in).functions.balanceOf(v["address"]).call()
        )
        if bal_in < amount_in_raw:
            raise HTTPException(
                400, f"insufficient vault balance: have {bal_in}, need {amount_in_raw}"
            )

        fee = int(req.fee) if req.fee is not None else None
        quote = self.pancake_swap_quote(
            alias,
            SwapQuoteRequest(
                alias=alias,
                token_in=req.token_in,
                token_out=req.token_out,
                amount_in=(
                    float(req.amount_in)
                    if resolved_mode == "token"
                    else float(amount_in_raw) / (10**dec_in)
                ),
                fee=fee,
                sqrt_price_limit_x96=req.sqrt_price_limit_x96,
                pool_override=req.pool_override,
            ),
        )
        fee_used = int(quote["best_fee"])
        amount_out_raw = int(quote["amount_out_raw"])
        if amount_out_raw <= 0:
            raise HTTPException(400, "quoter returned 0")

        bps = max(0, int(req.slippage_bps))
        min_out_raw = amount_out_raw * (10_000 - bps) // 10_000

        fn = ad_vault.fn_vault_swap_exact_in(
            router=Web3.to_checksum_address(s.PANCAKE_V3_ROUTER),
            token_in=req.token_in,
            token_out=req.token_out,
            fee=fee_used,
            amount_in_raw=amount_in_raw,
            min_out_raw=min_out_raw,
            sqrt_price_limit_x96=int(req.sqrt_price_limit_x96 or 0),
        )

        eth_usd_hint = estimate_eth_usd_from_pool(ad_pc)
        txs = TxService(v.get("rpc_url"))

        try:
            send_res = txs.send(
                fn,
                wait=True,
                gas_strategy="buffered",
                max_gas_usd=req.max_budget_usd,
                eth_usd_hint=eth_usd_hint,
            )
        except TransactionBudgetExceededError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": "BUDGET_EXCEEDED", "details": exc.__dict__},
            ) from exc
        except TransactionRevertedError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "ONCHAIN_REVERT",
                    "tx": exc.tx_hash,
                    "receipt": exc.receipt,
                    "msg": exc.msg,
                },
            ) from exc

        rcpt = send_res.get("receipt") or {}
        gas_used = int(rcpt.get("gasUsed") or 0)
        eff_price_wei = int(rcpt.get("effectiveGasPrice") or 0)
        gas_eth = (
            float((Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18))
            if gas_used and eff_price_wei
            else None
        )
        gas_usd = gas_eth * float(eth_usd_hint) if (gas_eth and eth_usd_hint) else None

        try:
            after = snapshot_status(ad_vault, vault_dex, alias)
        except Exception:  # noqa: BLE001
            after = {"warning": "status_unavailable_for_this_dex"}

        self._state_repo.append_history(
            dex_for_swap,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "swap_exact_in_pancake",
                "token_in": req.token_in,
                "token_out": req.token_out,
                "resolved_amount_mode": resolved_mode,
                "amount_in_raw": int(amount_in_raw),
                "quoted_out_raw": int(amount_out_raw),
                "min_out_raw": int(min_out_raw),
                "fee_used": int(fee_used),
                "slippage_bps": int(req.slippage_bps),
                "tx": send_res["tx_hash"],
                "gas_used": gas_used,
                "effective_gas_price_wei": eff_price_wei,
                "gas_eth": gas_eth,
                "gas_usd": gas_usd,
                "gas_budget_check": send_res.get("gas_budget_check"),
                "send_res": send_res,
                "pool_used": quote.get("pool_used"),
                "value_at_sqrt_after_usd": quote["value_at_sqrt_after_usd"],
            },
        )

        return {
            "tx": send_res["tx_hash"],
            "tick_spacing_used": int(fee_used),
            "resolved_amount_mode": resolved_mode,
            "amount_in_raw": int(amount_in_raw),
            "quoted_out_raw": int(amount_out_raw),
            "min_out_raw": int(min_out_raw),
            "value_at_sqrt_after_usd": quote["value_at_sqrt_after_usd"],
            "pool_used": quote.get("pool_used"),
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
            "budget": send_res.get("gas_budget_check"),
            "before": before,
            "after": after,
            "send_res": send_res,
        }
