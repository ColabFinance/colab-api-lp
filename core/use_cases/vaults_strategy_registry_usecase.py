from dataclasses import dataclass
from web3 import Web3

from config import get_settings
from adapters.chain.strategy_registry import StrategyRegistryAdapter
from core.services.tx_service import TxService


@dataclass
class VaultStrategyRegistryUseCase:
    """
    Orquestra StrategyRegistry + VaultFactory.

    - Leituras de Strategy (getStrategy)
    - Tx de criação de ClientVault (user)
    - Tx admin de Strategy (register/update/active)
    - Tx admin de VaultFactory (executor/defaults/feeCollector)
    """

    w3: Web3
    registry: StrategyRegistryAdapter
    txs: TxService

    @classmethod
    def from_settings(cls) -> "VaultStrategyRegistryUseCase":
        s = get_settings()
        w3 = Web3(Web3.HTTPProvider(s.RPC_URL_DEFAULT))
        registry = StrategyRegistryAdapter(w3=w3, address=s.STRATEGY_REGISTRY_ADDRESS)
        txs = TxService(s.RPC_URL_DEFAULT)
        return cls(w3=w3, registry=registry, txs=txs)

    # ------------------------------------------------------------------ #
    # Registry - views
    # ------------------------------------------------------------------ #

    def get_strategy(self, strategy_id: int) -> dict:
        return self.registry.get_strategy(strategy_id)

    def is_strategy_active(self, strategy_id: int) -> bool:
        return self.registry.is_strategy_active(strategy_id)

    # ------------------------------------------------------------------ #
    # Registry - admin tx
    # ------------------------------------------------------------------ #

    def register_strategy(
        self,
        *,
        adapter: str,
        dex_router: str,
        token0: str,
        token1: str,
        name: str,
        description: str,
    ) -> dict:
        fn = self.registry.fn_register_strategy(
            adapter=adapter,
            dex_router=dex_router,
            token0=token0,
            token1=token1,
            name=name,
            description=description,
        )

        res = self.txs.send(fn, wait=True, gas_strategy="buffered")
        strategy_id = self.registry.parse_strategy_registered_strategy_id(res.get("receipt") or {})

        res["result"] = {
            "strategy_id": strategy_id,
            "adapter": adapter,
            "dex_router": dex_router,
            "token0": token0,
            "token1": token1,
            "name": name,
            "description": description,
        }
        return res

    def update_strategy(
        self,
        *,
        strategy_id: int,
        adapter: str,
        dex_router: str,
        token0: str,
        token1: str,
        name: str,
        description: str,
    ) -> dict:
        fn = self.registry.fn_update_strategy(
            strategy_id=strategy_id,
            adapter=adapter,
            dex_router=dex_router,
            token0=token0,
            token1=token1,
            name=name,
            description=description,
        )

        res = self.txs.send(fn, wait=True, gas_strategy="buffered")
        res["result"] = {
            "strategy_id": int(strategy_id),
            "adapter": adapter,
            "dex_router": dex_router,
            "token0": token0,
            "token1": token1,
            "name": name,
            "description": description,
        }
        return res

    def set_strategy_active(self, *, strategy_id: int, active: bool) -> dict:
        fn = self.registry.fn_set_strategy_active(strategy_id=strategy_id, active=active)

        res = self.txs.send(fn, wait=True, gas_strategy="buffered")
        res["result"] = {"strategy_id": int(strategy_id), "active": bool(active)}
        return res
