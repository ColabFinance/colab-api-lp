from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Optional, Sequence

from eth_account import Account
from web3 import Web3
from web3.contract.contract import ContractFunction

from config import get_settings
from core.domain.enums.tx_enums import GasStrategy
from core.services.utils import to_json_safe
from core.services.exceptions import TransactionBudgetExceededError, TransactionRevertedError

@dataclass
class _BudgetBlock:
    max_gas_usd: Optional[float]
    eth_usd_hint: Optional[float]
    usd_estimated_upper_bound: Optional[float]
    budget_exceeded: bool

    def as_dict(self) -> dict:
        return {
            "max_gas_usd": self.max_gas_usd,
            "eth_usd_hint": self.eth_usd_hint,
            "usd_estimated_upper_bound": self.usd_estimated_upper_bound,
            "budget_exceeded": self.budget_exceeded,
        }
        
class TxService:
    """
    High-level transaction sender for vault ops.

    Responsibilities:
    - Build, sign and broadcast contract calls.
    - Apply gas padding strategy.
    - Enforce optional gas cost budget in USD.
    - Wait for receipt (optional).
    - Normalize successful and failure results so callers can persist.
    """

    def __init__(self, rpc_url: str | None = None):
        s = get_settings()
        self.w3 = Web3(Web3.HTTPProvider(rpc_url or s.RPC_URL_DEFAULT))
        self.pk = s.PRIVATE_KEY
        self.account = Account.from_key(self.pk)

    def sender_address(self) -> str:
        return self.account.address

    # ---------- internal helpers ----------

    def _next_nonce(self) -> int:
        return self.w3.eth.get_transaction_count(self.account.address, "pending")

    def _estimate_with_strategy(self, tx: dict, strategy: GasStrategy) -> int:
        """
        Calls estimateGas(tx) and applies a safety buffer depending on strategy.
        Falls back to a static 300k if node estimation fails.
        """
        try:
            base_estimate = int(self.w3.eth.estimate_gas(tx))
        except Exception:
            base_estimate = 300_000

        if strategy == "default":
            return base_estimate
        if strategy == "buffered":
            return int(base_estimate * 1.25) + 10_000
        if strategy == "aggressive":
            return int(base_estimate * 1.5) + 25_000
        return base_estimate  # fallback

    def _finalize_fee_fields(self, tx: dict) -> dict:
        """
        If the caller didn't specify EIP-1559 style fields, fallback to legacy gasPrice.
        Base supports legacy gasPrice.
        """
        if "maxFeePerGas" in tx or "maxPriorityFeePerGas" in tx:
            return tx
        if "gasPrice" not in tx:
            tx["gasPrice"] = self.w3.eth.gas_price
        return tx

    def _build_tx_dict(self, fn: ContractFunction, value_wei: int) -> dict:
        """
        Builds the bare transaction dict with from/nonce/value but no gas limit yet.
        """
        base_tx = {
            "from":  self.account.address,
            "nonce": self._next_nonce(),
            "value": int(value_wei or 0),
        }
        return fn.build_transaction(base_tx)

    def _sign_and_send(self, tx: dict) -> str:
        signed = self.w3.eth.account.sign_transaction(tx, self.pk)
        txh = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return txh.hex()

    def _wait_receipt(self, tx_hash: str) -> dict:
        rcpt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return dict(rcpt)

    def _budget_check(
        self,
        *,
        gas_limit: int,
        gas_price_wei: int,
        max_gas_usd: Optional[float],
        eth_usd_hint: Optional[float],
    ) -> _BudgetBlock:
        budget = _BudgetBlock(
            max_gas_usd=max_gas_usd,
            eth_usd_hint=eth_usd_hint,
            usd_estimated_upper_bound=None,
            budget_exceeded=False,
        )

        if max_gas_usd is None:
            return budget

        if eth_usd_hint is None or eth_usd_hint <= 0:
            raise TransactionBudgetExceededError(
                est_gas_limit=int(gas_limit),
                gas_price_wei=int(gas_price_wei),
                eth_usd=0.0,
                usd_estimated=0.0,
                usd_budget=float(max_gas_usd),
            )

        gas_cost_eth = (Decimal(gas_limit) * Decimal(gas_price_wei)) / Decimal(10**18)
        gas_cost_usd = float(gas_cost_eth * Decimal(eth_usd_hint))
        budget.usd_estimated_upper_bound = gas_cost_usd

        if gas_cost_usd > float(max_gas_usd):
            budget.budget_exceeded = True
            raise TransactionBudgetExceededError(
                est_gas_limit=int(gas_limit),
                gas_price_wei=int(gas_price_wei),
                eth_usd=float(eth_usd_hint),
                usd_estimated=float(gas_cost_usd),
                usd_budget=float(max_gas_usd),
            )

        return budget
    
    def _base_response(
        self,
        *,
        tx_hash: str,
        broadcasted: bool,
        status: Optional[int],
        receipt: Optional[dict],
        gas_limit: int,
        gas_price_wei: int,
        budget: _BudgetBlock,
        gas_cost_usd: Optional[float] = None,
    ) -> dict:
        gas_used = int((receipt or {}).get("gasUsed") or 0)
        eff_price_wei = int((receipt or {}).get("effectiveGasPrice") or 0)

        cost_eth = None
        if gas_used and eff_price_wei:
            cost_eth = float((Decimal(gas_used) * Decimal(eff_price_wei)) / Decimal(10**18))

        return to_json_safe(
            {
                "tx_hash": tx_hash,
                "broadcasted": bool(broadcasted),
                "status": status,
                "receipt": receipt,
                "gas": {
                    "limit": int(gas_limit),
                    "used": int(gas_used),
                    "price_wei": int(gas_price_wei),
                    "effective_price_wei": int(eff_price_wei),
                    "cost_eth": cost_eth,
                    "cost_usd": gas_cost_usd,
                },
                "budget": budget.as_dict(),
                "result": {},
                "ts": datetime.now(UTC).isoformat(),
            }
        )
        
    # ---------- public API ----------

    def send(
        self,
        fn: ContractFunction,
        *,
        wait: bool = False,
        value: int = 0,
        gas_limit: Optional[int] = None,
        gas_strategy: GasStrategy = GasStrategy.BUFFERED,
        max_gas_usd: Optional[float] = None,
        eth_usd_hint: Optional[float] = None,
    ) -> dict:
        """
        Broadcasts a state-changing transaction on-chain for a given contract function.

        Args:
            fn: Already-parameterized ContractFunction from web3.py
            wait: If True, block until mined and attach receipt + status
            value: ETH value (wei) to send along with the call
            gas_limit: Force a manual gas limit instead of estimating
            gas_strategy: "default" | "buffered" | "aggressive"
            max_gas_usd:
                Optional absolute budget in USD you're willing to burn JUST IN GAS
                for this tx. If predicted upper-bound > this number, we DO NOT
                broadcast; we raise TransactionBudgetExceededError instead.
            eth_usd_hint:
                Caller-supplied price of 1 ETH in USD (float).
                Ex: se pool tiver par WETH/USDC você já sabe o preço.
                Required if you pass max_gas_usd, otherwise we can't price it.

        Returns (on success OR if wait=False broadcasted ok):
            {
              "tx_hash": "0x..",
              "broadcasted": True,
              "receipt": {...} OR None,
              "status": int|None,        # 1 or 0 if mined, None if wait=False
              "gas_limit_used": int,
              "gas_price_wei": int,
              "gas_budget_check": {
                  "max_gas_usd": float|None,
                  "eth_usd_hint": float|None,
                  "usd_estimated_upper_bound": float|None,
                  "budget_exceeded": bool
              }
            }

        Raises:
            TransactionBudgetExceededError:
                - Fired BEFORE sending, no tx executed on-chain.
            TransactionRevertedError:
                - Fired AFTER mined, status==0 (revert/out-of-gas/require fail).
        """

        # 1) Build base tx (without gas limit)
        tx = self._build_tx_dict(fn, value_wei=value)

        # 2) Gas limit strategy
        if gas_limit is not None:
            final_gas_limit = int(gas_limit)
        else:
            final_gas_limit = self._estimate_with_strategy(tx, gas_strategy)
        tx["gas"] = final_gas_limit

        # 3) gasPrice / EIP-1559 fee fields
        tx = self._finalize_fee_fields(tx)
        gas_price_wei = int(tx.get("gasPrice", 0))

        budget = self._budget_check(
            gas_limit=final_gas_limit,
            gas_price_wei=gas_price_wei,
            max_gas_usd=max_gas_usd,
            eth_usd_hint=eth_usd_hint,
        )

        tx_hash = self._sign_and_send(tx)

        if not wait:
            return self._base_response(
                tx_hash=tx_hash,
                broadcasted=True,
                status=None,
                receipt=None,
                gas_limit=final_gas_limit,
                gas_price_wei=gas_price_wei,
                budget=budget,
            )

        rcpt = self._wait_receipt(tx_hash)
        status = int(rcpt.get("status", 0))

        if status == 0:
            raise TransactionRevertedError(
                tx_hash=tx_hash,
                receipt=to_json_safe(rcpt),
                msg="Transaction reverted (status=0). Possibly out-of-gas or require() failed",
                budget_block=budget.as_dict(),
            )

        return self._base_response(
            tx_hash=tx_hash,
            broadcasted=True,
            status=status,
            receipt=rcpt,
            gas_limit=final_gas_limit,
            gas_price_wei=gas_price_wei,
            budget=budget,
        )

    def deploy(
        self,
        *,
        abi: list,
        bytecode: str,
        ctor_args: Sequence[Any] = (),
        wait: bool = True,
        gas_limit: Optional[int] = None,
        gas_strategy: GasStrategy = GasStrategy.BUFFERED,
        value: int = 0,
        max_gas_usd: Optional[float] = None,
        eth_usd_hint: Optional[float] = None,
    ) -> dict:
        ContractFactory = self.w3.eth.contract(abi=abi, bytecode=bytecode)

        build_tx = ContractFactory.constructor(*list(ctor_args)).build_transaction(
            {
                "from": self.account.address,
                "nonce": self._next_nonce(),
                "value": int(value or 0),
            }
        )

        if gas_limit is not None:
            final_gas_limit = int(gas_limit)
        else:
            try:
                base_estimate = int(self.w3.eth.estimate_gas(build_tx))
            except Exception:
                base_estimate = 500_000

            if gas_strategy == "default":
                final_gas_limit = base_estimate
            elif gas_strategy == "buffered":
                final_gas_limit = int(base_estimate * 1.25) + 10_000
            else:
                final_gas_limit = int(base_estimate * 1.5) + 25_000

        build_tx["gas"] = final_gas_limit

        if "gasPrice" not in build_tx and "maxFeePerGas" not in build_tx:
            build_tx["gasPrice"] = self.w3.eth.gas_price
        gas_price_wei = int(build_tx.get("gasPrice", 0))

        budget = self._budget_check(
            gas_limit=final_gas_limit,
            gas_price_wei=gas_price_wei,
            max_gas_usd=max_gas_usd,
            eth_usd_hint=eth_usd_hint,
        )

        signed = self.w3.eth.account.sign_transaction(build_tx, self.pk)
        txh = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        tx_hash = txh.hex()

        if not wait:
            base = self._base_response(
                tx_hash=tx_hash,
                broadcasted=True,
                status=None,
                receipt=None,
                gas_limit=final_gas_limit,
                gas_price_wei=gas_price_wei,
                budget=budget,
            )
            base["result"] = {"contract_address": None}
            return to_json_safe(base)

        rcpt = dict(self.w3.eth.wait_for_transaction_receipt(txh))
        status = int(rcpt.get("status", 0))

        if status == 0:
            raise TransactionRevertedError(
                tx_hash=tx_hash,
                receipt=to_json_safe(rcpt),
                msg="Deploy reverted (status=0)",
                budget_block=budget.as_dict(),
            )

        base = self._base_response(
            tx_hash=tx_hash,
            broadcasted=True,
            status=status,
            receipt=rcpt,
            gas_limit=final_gas_limit,
            gas_price_wei=gas_price_wei,
            budget=budget,
        )
        base["result"] = {"contract_address": rcpt.get("contractAddress")}
        return to_json_safe(base)
