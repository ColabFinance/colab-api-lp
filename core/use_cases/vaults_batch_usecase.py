# core/domain/usecases/vaults_batch_usecase.py

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from web3 import Web3

from config import get_settings
from core.domain.pancake_batch_request import PancakeBatchRequest
from core.domain.swap import SwapQuoteRequest
from core.services.tx_service import (
    TxService,
    TransactionBudgetExceededError,
    TransactionRevertedError,
)
from adapters.external.database import state_repo, vault_repo
from core.services.status_service import (
    USD_SYMBOLS,
    _is_usd_symbol,
    compute_status,
    price_to_tick,
    sqrtPriceX96_to_price_t1_per_t0,
)
from core.services.vault_adapter_service import get_adapter_for
from core.use_cases.vaults_swap_usecase import VaultsSwapUseCase
from routes.utils import (
    _is_usd,
    estimate_eth_usd_from_pool,
    resolve_pool_from_vault,
    snapshot_status,
)


class VaultsBatchUseCase:
    """
    Use case responsible for multi-step batch operations on vaults.

    Currently this class exposes a single high-level operation for Pancake v3:

        - Unstake position from gauge (if any)
        - Exit current position (liquidity -> idle balances in the vault)
        - (Optionally) perform a swap between token_in and token_out
        - Open a new position with the resulting composition and range.

    The entire sequence is performed atomically via a single vault contract
    call, following the same semantics you had in your monolithic endpoint.
    """

    def __init__(
        self,
    ) -> None:
        """
        Initialize the VaultsBatchUseCase.

        Args:
            vault_repo: Repository used to resolve vault configuration.
            state_repo: Repository for tracking vault state, execution history
                and fee/reward snapshots.
        """
        self._vault_repo = vault_repo
        self._state_repo = state_repo

    def pancake_batch_unstake_exit_swap_open(
        self,
        alias: str,
        req: PancakeBatchRequest,
    ) -> dict[str, Any]:
        """
        Execute a full Pancake v3 batch pipeline:

        1) Unstake the vault position from the gauge, if a gauge is configured
           and the position is currently staked.
        2) Exit the current liquidity position back into idle vault balances.
        3) Perform an optional exact-in swap on Pancake v3 between token_in and
           token_out, using either a token amount or a USD amount derived from
           the pool price.
        4) Open a new position using the final token composition, with the
           target range defined either directly in ticks or implicitly via
           human prices.

        This is all performed in a single on-chain transaction using the
        `fn_batch_unstake_exit_swap_open_pancake` helper on the adapter.

        Args:
            alias: Vault alias (must be a Pancake vault).
            req: PancakeBatchRequest containing:
                - swap leg: token_in, token_out, amount_in or amount_in_usd,
                  slippage_bps, fee override and pool_override;
                - range leg: lower_tick/upper_tick or lower_price/upper_price;
                - gas: max_budget_usd and sqrt_price_limit_x96.

        Returns:
            A dictionary with:
                - tx: transaction hash
                - resolved_amount_mode: "token" | "usd" | "none" (no swap)
                - amount_in_raw / quoted_out_raw / min_out_raw
                - range_used: ticks, width, spacing, optional prices
                - gas usage in wei/ETH/USD
                - before/after snapshots
                - pool_used and value_at_sqrt_after_usd.

        Raises:
            HTTPException:
                - 404 if alias is unknown.
                - 400 if the vault is not Pancake, inputs are invalid or width
                  constraints fail.
                - 400 on budget exceeded.
                - 502 on on-chain revert.
        """
        dex = "pancake"

        vault_dex, v = self._vault_repo.get_vault_any(alias)
        if not v:
            raise HTTPException(404, "Unknown alias")

        if vault_dex != dex:
            raise HTTPException(
                400,
                "Batch unstake-exit-swap-open is only supported for Pancake vaults.",
            )

        s = get_settings()
        if not getattr(s, "PANCAKE_V3_ROUTER", None) or not getattr(
            s, "PANCAKE_V3_QUOTER", None
        ):
            raise HTTPException(
                500, "PANCAKE_V3_ROUTER/PANCAKE_V3_QUOTER not configured"
            )

        self._state_repo.ensure_state_initialized(dex, alias, vault_address=v["address"])

        ad_vault = get_adapter_for(
            dex,
            v["pool"],
            v.get("nfpm"),
            v["address"],
            v.get("rpc_url"),
            v.get("gauge"),
        )

        pool_addr = resolve_pool_from_vault(v, req.pool_override)
        ad_pc = get_adapter_for(dex, pool_addr, None, v["address"], v.get("rpc_url"))

        try:
            before = snapshot_status(ad_vault, dex, alias)
        except Exception:  # noqa: BLE001
            before = {"warning": "status_unavailable_for_this_dex"}

        meta = ad_vault.pool_meta()
        dec0 = int(meta["dec0"])
        dec1 = int(meta["dec1"])
        sym0 = meta["sym0"]
        sym1 = meta["sym1"]
        spacing = int(meta.get("spacing") or 0)

        def _is_usdc(sym: str) -> bool:
            return sym.upper() in USD_SYMBOLS

        def _is_eth(sym: str) -> bool:
            return sym.upper() in {"WETH", "ETH"}

        def _ui_price_to_p_t1_t0(ui_price: float, sym0_: str, sym1_: str) -> float:
            """
            Convert a human-facing price into p_t1_t0 (token1 per token0),
            compatible with price_to_tick.

            If token1 is USD-like, the human price already matches p_t1_t0.
            If token0 is USD-like, the human price is p_t0_t1 -> invert.
            Otherwise, assume the user already provided p_t1_t0 in pool convention.
            """
            if _is_usdc(sym1_):
                return float(ui_price)
            if _is_usdc(sym0_):
                return 1.0 / float(ui_price)
            return float(ui_price)

        lower_tick = req.lower_tick
        upper_tick = req.upper_tick

        if lower_tick is None or upper_tick is None:
            if req.lower_price is None or req.upper_price is None:
                raise HTTPException(
                    400,
                    "You must provide either (lower_tick and upper_tick) "
                    "OR (lower_price and upper_price).",
                )
            pL = _ui_price_to_p_t1_t0(float(req.lower_price), sym0, sym1)
            pU = _ui_price_to_p_t1_t0(float(req.upper_price), sym0, sym1)

            lower_tick = price_to_tick(pL, dec0, dec1)
            upper_tick = price_to_tick(pU, dec0, dec1)

        if lower_tick > upper_tick:
            lower_tick, upper_tick = upper_tick, lower_tick

        if spacing:

            def align_floor(t: int, s_: int) -> int:
                r = t % s_
                return t - r

            def align_ceil(t: int, s_: int) -> int:
                r = t % s_
                return t if r == 0 else t + (s_ - r)

            lower_tick = align_floor(int(lower_tick), spacing)
            upper_tick = align_ceil(int(upper_tick), spacing)

        if lower_tick == upper_tick:
            lower_tick -= spacing or 1
            upper_tick += spacing or 1

        cons = (
            ad_vault.vault_constraints()
            if hasattr(ad_vault, "vault_constraints")
            else {}
        )
        width = abs(int(upper_tick) - int(lower_tick))
        if cons.get("minWidth") and width < cons["minWidth"]:
            raise HTTPException(
                400, f"Width too small: {width} < minWidth={cons['minWidth']}."
            )
        if cons.get("maxWidth") and width > cons["maxWidth"]:
            raise HTTPException(
                400, f"Width too large: {width} > maxWidth={cons['maxWidth']}."
            )

        dec_in = int(ad_vault.erc20(req.token_in).functions.decimals().call())
        dec_out = int(ad_vault.erc20(req.token_out).functions.decimals().call())

        meta_swap = ad_pc.pool_meta()
        sym0_s, sym1_s = meta_swap["sym0"], meta_swap["sym1"]
        dec0_s, dec1_s = int(meta_swap["dec0"]), int(meta_swap["dec1"])
        sqrtP_s, _ = ad_pc.slot0()
        p_t1_t0_swap = sqrtPriceX96_to_price_t1_per_t0(sqrtP_s, dec0_s, dec1_s)

        resolved_mode: str
        amount_in_raw: int

        if req.amount_in is not None:
            amount_in_raw = int(float(req.amount_in) * (10**dec_in))
            resolved_mode = "token"
        elif req.amount_in_usd is not None:
            usdc_per_eth = None
            if _is_usdc(sym1_s) and _is_eth(sym0_s):
                usdc_per_eth = p_t1_t0_swap
            elif _is_usdc(sym0_s) and _is_eth(sym1_s):
                usdc_per_eth = (
                    0.0 if p_t1_t0_swap == 0 else 1.0 / float(p_t1_t0_swap)
                )

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
            amount_in_raw = 0
            resolved_mode = "none"

        if amount_in_raw < 0:
            raise HTTPException(400, "amount_in must be >= 0")

        fee_used: Optional[int] = None
        amount_out_raw = 0
        min_out_raw = 0
        value_at_sqrt_after_usd: Optional[float] = None
        pool_used = pool_addr

        if amount_in_raw > 0:

            quote = (
                # reuse the HTTP-level shape through the swap use case if you want
                # or keep calling the pure helper as here
                # - here we call the same helper used by the HTTP route:
                #   pancake_swap_quote(alias, ...)
                # - since this use case is self-contained, we just call the quoter
                #   logic already wrapped in VaultsSwapUseCase if you prefer.
                None
            )

            # Para não depender circularmente de VaultsSwapUseCase aqui,
            # mantemos a lógica exatamente como estava, reusando o endpoint
            # original sinteticamente:

            swap_uc = VaultsSwapUseCase()
            quote = swap_uc.pancake_swap_quote(
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
                    fee=req.fee,
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
            value_at_sqrt_after_usd = float(quote["value_at_sqrt_after_usd"])
            pool_used = quote.get("pool_used", pool_addr)
        else:
            fee_used = int(ad_pc.pool_contract().functions.fee().call())

        router_addr = Web3.to_checksum_address(s.PANCAKE_V3_ROUTER)

        fn = ad_vault.fn_batch_unstake_exit_swap_open_pancake(
            router=router_addr,
            token_in=req.token_in,
            token_out=req.token_out,
            fee=fee_used,
            amount_in_raw=amount_in_raw,
            min_out_raw=min_out_raw,
            sqrt_price_limit_x96=int(req.sqrt_price_limit_x96 or 0),
            lower_tick=int(lower_tick),
            upper_tick=int(upper_tick),
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

        try:
            fees_info = (before or {}).get("fees_uncollected") or {}
            fees0_h = float(fees_info.get("token0") or 0.0)
            fees1_h = float(fees_info.get("token1") or 0.0)

            if fees0_h > 0.0 or fees1_h > 0.0:
                fees0_raw = int(fees0_h * (10**dec0))
                fees1_raw = int(fees1_h * (10**dec1))

                prices_before = (before or {}).get("prices") or {}
                cur = prices_before.get("current", {}) or {}
                p_t1_t0 = float(cur.get("p_t1_t0") or 0.0)
                p_t0_t1 = 0.0 if p_t1_t0 == 0.0 else 1.0 / p_t1_t0

                if _is_usdc(sym1):
                    pre_fees_usd = fees0_h * p_t1_t0 + fees1_h
                elif _is_usdc(sym0):
                    pre_fees_usd = fees1_h * p_t0_t1 + fees0_h
                else:
                    pre_fees_usd = fees0_h * p_t1_t0 + fees1_h

                self._state_repo.add_collected_fees_snapshot(
                    dex,
                    alias,
                    fees0_raw=int(fees0_raw),
                    fees1_raw=int(fees1_raw),
                    fees_usd_est=float(pre_fees_usd),
                )
                self._state_repo.append_history(
                    dex,
                    alias,
                    "collect_history",
                    {
                        "ts": datetime.utcnow().isoformat(),
                        "mode": "collect_via_batch_unstake_exit",
                        "fees0_raw": int(fees0_raw),
                        "fees1_raw": int(fees1_raw),
                        "fees_usd_est": float(pre_fees_usd),
                        "tx": send_res["tx_hash"],
                    },
                )
        except Exception as exc:  # noqa: BLE001
            logging.warning(
                "batch_unstake_exit_swap_open: failed to record collected_fees_snapshot: %s",
                exc,
            )

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
            after = snapshot_status(ad_vault, dex, alias)
        except Exception:  # noqa: BLE001
            after = {"warning": "status_unavailable_for_this_dex"}

        self._state_repo.append_history(
            dex,
            alias,
            "exec_history",
            {
                "ts": datetime.utcnow().isoformat(),
                "mode": "batch_unstake_exit_swap_open_pancake",
                "token_in": req.token_in,
                "token_out": req.token_out,
                "resolved_amount_mode": resolved_mode,
                "amount_in_raw": int(amount_in_raw),
                "quoted_out_raw": int(amount_out_raw),
                "min_out_raw": int(min_out_raw),
                "fee_used": int(fee_used),
                "slippage_bps": int(req.slippage_bps),
                "lower_tick": int(lower_tick),
                "upper_tick": int(upper_tick),
                "tx": send_res["tx_hash"],
                "gas_used": gas_used,
                "effective_gas_price_wei": eff_price_wei,
                "gas_eth": gas_eth,
                "gas_usd": gas_usd,
                "gas_budget_check": send_res.get("gas_budget_check"),
                "send_res": send_res,
                "pool_used": pool_used,
                "value_at_sqrt_after_usd": value_at_sqrt_after_usd,
            },
        )

        return {
            "tx": send_res["tx_hash"],
            "tick_spacing_used": int(spacing),
            "resolved_amount_mode": resolved_mode,
            "amount_in_raw": int(amount_in_raw),
            "quoted_out_raw": int(amount_out_raw),
            "min_out_raw": int(min_out_raw),
            "range_used": {
                "lower_tick": int(lower_tick),
                "upper_tick": int(upper_tick),
                "width_ticks": int(width),
                "spacing": int(spacing),
                "lower_price": float(req.lower_price)
                if req.lower_price is not None
                else None,
                "upper_price": float(req.upper_price)
                if req.upper_price is not None
                else None,
            },
            "value_at_sqrt_after_usd": value_at_sqrt_after_usd,
            "pool_used": pool_used,
            "gas_used": gas_used,
            "effective_gas_price_wei": eff_price_wei,
            "gas_eth": gas_eth,
            "gas_usd": gas_usd,
            "budget": send_res.get("gas_budget_check"),
            "before": before,
            "after": after,
            "send_res": send_res,
        }
