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

    def get_status(self, *, alias_or_address: str) -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        return self.status_svc.compute(vault_addr)

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
