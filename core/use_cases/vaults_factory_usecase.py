from dataclasses import dataclass
from typing import Any, Dict, Optional

from web3 import Web3

from config import get_settings
from adapters.chain.strategy_registry import StrategyRegistryAdapter
from adapters.chain.vault_factory import VaultFactoryAdapter
from core.services.tx_service import TxService


@dataclass
class VaultFactoryUseCase:
    w3: Web3
    registry: StrategyRegistryAdapter
    factory: VaultFactoryAdapter
    txs: TxService

    @classmethod
    def from_settings(cls) -> "VaultFactoryUseCase":
        s = get_settings()
        w3 = Web3(Web3.HTTPProvider(s.RPC_URL_DEFAULT))
        registry = StrategyRegistryAdapter(w3=w3, address=s.STRATEGY_REGISTRY_ADDRESS)
        factory = VaultFactoryAdapter(w3=w3, address=s.VAULT_FACTORY_ADDRESS)
        txs = TxService(s.RPC_URL_DEFAULT)
        return cls(w3=w3, registry=registry, factory=factory, txs=txs)

    # ---------------- views ----------------

    def get_factory_config(self) -> Dict[str, Any]:
        return self.factory.get_config()

    # ---------------- tx runners (signed by backend PK) ----------------

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

        # se você tiver evento VaultCreated, aqui você parseia e coloca vault_address.
        res["result"] = {
            "strategy_id": int(strategy_id),
            "owner_override": owner_override,
            "vault_address": None,
        }
        return res

    def set_executor(self, *, new_executor: str, gas_strategy: str = "buffered") -> Dict[str, Any]:
        fn = self.factory.fn_set_executor(new_executor=new_executor)
        res = self.txs.send(fn, wait=True, gas_strategy=gas_strategy)
        res["result"] = {"new_executor": new_executor}
        return res

    def set_fee_collector(self, *, new_collector: str, gas_strategy: str = "buffered") -> Dict[str, Any]:
        fn = self.factory.fn_set_fee_collector(new_collector=new_collector)
        res = self.txs.send(fn, wait=True, gas_strategy=gas_strategy)
        res["result"] = {"new_collector": new_collector}
        return res

    def set_defaults(
        self,
        *,
        cooldown_sec: int,
        max_slippage_bps: int,
        allow_swap: bool,
        gas_strategy: str = "buffered",
    ) -> Dict[str, Any]:
        fn = self.factory.fn_set_defaults(cooldown_sec=cooldown_sec, max_slippage_bps=max_slippage_bps, allow_swap=allow_swap)
        res = self.txs.send(fn, wait=True, gas_strategy=gas_strategy)
        res["result"] = {
            "cooldown_sec": int(cooldown_sec),
            "max_slippage_bps": int(max_slippage_bps),
            "allow_swap": bool(allow_swap),
        }
        return res
