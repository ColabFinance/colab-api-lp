from dataclasses import dataclass
from typing import Any, Dict, Optional

from web3 import Web3
from web3.exceptions import ABIFunctionNotFound

from adapters.chain.strategy_registry import StrategyRegistryAdapter
from adapters.chain.vault_factory import VaultFactoryAdapter
from config import get_settings
from adapters.chain.client_vault import ClientVaultAdapter
from core.services.tx_service import TxService
from core.services.vault_status_service import VaultStatusService


def _is_address_like(s: str) -> bool:
    return isinstance(s, str) and s.startswith("0x") and len(s) == 42


@dataclass
class VaultClientVaultUseCase:
    """
    ClientVault creation use case.

    Responsibilities:
    - Validate strategy exists/active on StrategyRegistry
    - Execute VaultFactory.createClientVault signed by backend PK
    """
    
    w3: Web3
    registry: StrategyRegistryAdapter
    factory: VaultFactoryAdapter
    txs: TxService
    status_svc: VaultStatusService
    
    @classmethod
    def from_settings(cls) -> "VaultClientVaultUseCase":
        s = get_settings()
        w3 = Web3(Web3.HTTPProvider(s.RPC_URL_DEFAULT))
        registry = StrategyRegistryAdapter(w3=w3, address=s.STRATEGY_REGISTRY_ADDRESS)
        factory = VaultFactoryAdapter(w3=w3, address=s.VAULT_FACTORY_ADDRESS)
        status_svc = VaultStatusService(w3=w3)
        txs = TxService(s.RPC_URL_DEFAULT)
        return cls(w3=w3, registry=registry, factory=factory, txs=txs, status_svc=status_svc)

    def create_client_vault(
        self,
        *,
        strategy_id: int,
        owner_override: Optional[str] = None,
        gas_strategy: str = "buffered",
    ) -> Dict[str, Any]:
        if not self.registry.is_strategy_active(strategy_id):
            raise ValueError("Strategy not active or does not exist on-chain")

        fn = self.factory.fn_create_client_vault(strategy_id=strategy_id, owner_override=owner_override)
        res = self.txs.send(fn, wait=True, gas_strategy=gas_strategy)

        res["result"] = {
            "strategy_id": int(strategy_id),
            "owner_override": owner_override,
            "vault_address": None,
        }
        return res
    
    def _resolve_vault_address(self, alias_or_address: str) -> str:
        if _is_address_like(alias_or_address):
            return Web3.to_checksum_address(alias_or_address)
        raise ValueError("Unknown vault alias (send the vault address in the path)")

    # -------- reads --------

    def get_status(self, *, alias_or_address: str) -> Dict[str, Any]:
        vault_addr = self._resolve_vault_address(alias_or_address)
        return self.status_svc.compute(vault_addr)


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
