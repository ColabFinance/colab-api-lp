from dataclasses import dataclass
from typing import Any, Dict, Optional

from web3 import Web3

from config import get_settings
from adapters.chain.strategy_registry import StrategyRegistryAdapter
from adapters.chain.vault_factory import VaultFactoryAdapter
from core.services.tx_service import TxService


@dataclass
class VaultFactoryUseCase:
    """
    VaultFactory admin use case only.

    Responsibilities:
    - Read VaultFactory config
    - Execute onlyOwner tx: setExecutor, setFeeCollector, setDefaults
    """
    
    w3: Web3
    factory: VaultFactoryAdapter
    txs: TxService

    @classmethod
    def from_settings(cls) -> "VaultFactoryUseCase":
        s = get_settings()
        w3 = Web3(Web3.HTTPProvider(s.RPC_URL_DEFAULT))
        registry = StrategyRegistryAdapter(w3=w3, address=s.STRATEGY_REGISTRY_ADDRESS)
        factory = VaultFactoryAdapter(w3=w3, address=s.VAULT_FACTORY_ADDRESS)
        txs = TxService(s.RPC_URL_DEFAULT)
        return cls(w3=w3, factory=factory, txs=txs)

    # ---------------- views ----------------

    def get_factory_config(self) -> Dict[str, Any]:
        return self.factory.get_config()

    # ---------------- tx runners (signed by backend PK) ----------------

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
