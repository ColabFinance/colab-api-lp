from dataclasses import dataclass
from typing import Any, Dict

from web3 import Web3
from web3.exceptions import ABIFunctionNotFound

from config import get_settings
from adapters.chain.client_vault import ClientVaultAdapter
from core.services.tx_service import TxService
from core.services.vault_status_service import VaultStatusService


def _is_address_like(s: str) -> bool:
    return isinstance(s, str) and s.startswith("0x") and len(s) == 42


@dataclass
class VaultClientVaultUseCase:
    w3: Web3
    txs: TxService
    status_svc: VaultStatusService

    @classmethod
    def from_settings(cls) -> "VaultClientVaultUseCase":
        s = get_settings()
        w3 = Web3(Web3.HTTPProvider(s.RPC_URL_DEFAULT))
        txs = TxService(s.RPC_URL_DEFAULT)
        status_svc = VaultStatusService(w3=w3)
        return cls(w3=w3, txs=txs, status_svc=status_svc)

    def _resolve_vault_address(self, alias_or_address: str) -> str:
        if _is_address_like(alias_or_address):
            return Web3.to_checksum_address(alias_or_address)
        raise ValueError("Unknown vault alias (send the vault address in the path)")

    # -------- reads --------

    def get_status(self, *, alias_or_address: str) -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        return self.status_svc.compute(vault_addr)

    # -------- owner-tx (optional in api-lp; official path is front) --------

    def set_automation_enabled(self, *, alias_or_address: str, enabled: bool, gas_strategy: str = "buffered") -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)
        try:
            fn = v.fn_set_automation_enabled(enabled=enabled)
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose setAutomationEnabled") from e
        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

    def set_automation_config(
        self,
        *,
        alias_or_address: str,
        cooldown_sec: int,
        max_slippage_bps: int,
        allow_swap: bool,
        gas_strategy: str = "buffered",
    ) -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)
        try:
            fn = v.fn_set_automation_config(
                cooldown_sec=cooldown_sec,
                max_slippage_bps=max_slippage_bps,
                allow_swap=allow_swap,
            )
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose setAutomationConfig") from e
        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

    def collect(self, *, alias_or_address: str, gas_strategy: str = "buffered") -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)
        try:
            fn = v.fn_collect()
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose collectToVault") from e
        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

    def exit_to_vault(self, *, alias_or_address: str, gas_strategy: str = "buffered") -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)
        try:
            fn = v.fn_exit_to_vault()
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose exitPositionToVault") from e
        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

    def exit_withdraw_all(self, *, alias_or_address: str, to: str, gas_strategy: str = "buffered") -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)
        try:
            fn = v.fn_exit_withdraw_all(to_addr=to)
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose exitPositionAndWithdrawAll") from e
        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

    def open_initial_position(self, *, alias_or_address: str, lower_tick: int, upper_tick: int, gas_strategy: str = "buffered") -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)
        if int(lower_tick) >= int(upper_tick):
            raise ValueError("Invalid tick range: lower_tick must be < upper_tick")
        try:
            fn = v.fn_open_initial_position(lower_tick=lower_tick, upper_tick=upper_tick)
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose openInitialPosition") from e
        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

    def rebalance_with_caps(
        self,
        *,
        alias_or_address: str,
        lower_tick: int,
        upper_tick: int,
        cap0: int,
        cap1: int,
        gas_strategy: str = "buffered",
    ) -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)
        if int(lower_tick) >= int(upper_tick):
            raise ValueError("Invalid tick range: lower_tick must be < upper_tick")
        try:
            fn = v.fn_rebalance_with_caps(lower_tick=lower_tick, upper_tick=upper_tick, cap0=cap0, cap1=cap1)
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose rebalanceWithCaps") from e
        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

    def stake(self, *, alias_or_address: str, gas_strategy: str = "buffered") -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)
        try:
            fn = v.fn_stake()
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose stake") from e
        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

    def unstake(self, *, alias_or_address: str, gas_strategy: str = "buffered") -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)
        try:
            fn = v.fn_unstake()
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose unstake") from e
        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

    def claim_rewards(self, *, alias_or_address: str, gas_strategy: str = "buffered") -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)
        try:
            fn = v.fn_claim_rewards()
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose claimRewards") from e
        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

    def swap_exact_in_pancake(
        self,
        *,
        alias_or_address: str,
        token_in: str,
        token_out: str,
        fee: int,
        amount_in: int,
        amount_out_min: int,
        sqrt_price_limit_x96: int,
        gas_strategy: str = "buffered",
    ) -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)
        try:
            fn = v.fn_swap_exact_in_pancake(
                token_in=token_in,
                token_out=token_out,
                fee=fee,
                amount_in=amount_in,
                amount_out_min=amount_out_min,
                sqrt_price_limit_x96=sqrt_price_limit_x96,
            )
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose swapExactInPancake") from e
        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

    # -------- executor-tx (required in api-lp) --------

    def auto_rebalance_pancake(
        self,
        *,
        alias_or_address: str,
        params: Dict[str, Any],
        gas_strategy: str = "buffered",
    ) -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        v = ClientVaultAdapter(w3=self.w3, address=vault_addr)

        required = [
            "newLowerTick",
            "newUpperTick",
            "fee",
            "tokenIn",
            "tokenOut",
            "swapAmountIn",
            "swapAmountOutMin",
            "sqrtPriceLimitX96",
        ]
        for k in required:
            if k not in params:
                raise ValueError(f"Missing param: {k}")

        if int(params["newLowerTick"]) >= int(params["newUpperTick"]):
            raise ValueError("Invalid tick range: newLowerTick must be < newUpperTick")

        try:
            fn = v.fn_auto_rebalance_pancake(params)
        except ABIFunctionNotFound as e:
            raise ValueError("Vault does not expose autoRebalancePancake") from e

        return self.txs.send(fn, wait=True, gas_strategy=gas_strategy)
