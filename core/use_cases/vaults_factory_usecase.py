# core/use_cases/vaults_factory_usecase.py
from dataclasses import dataclass

from web3 import Web3

from config import get_settings
from adapters.chain.strategy_registry import StrategyRegistryAdapter
from adapters.chain.vault_factory import VaultFactoryAdapter


@dataclass
class VaultFactoryUseCase:
    """
    Orquestra StrategyRegistry + VaultFactory.

    - Leituras de Strategy (getStrategy)
    - Tx de criação de ClientVault (user)
    - Tx admin de Strategy (register/update/active)
    - Tx admin de VaultFactory (executor/defaults/feeCollector)
    """

    w3: Web3
    registry: StrategyRegistryAdapter
    factory: VaultFactoryAdapter

    @classmethod
    def from_settings(cls) -> "VaultFactoryUseCase":
        settings = get_settings()
        w3 = Web3(Web3.HTTPProvider(settings.RPC_URL_DEFAULT))

        registry = StrategyRegistryAdapter(
            w3=w3, address=settings.STRATEGY_REGISTRY_ADDRESS
        )
        factory = VaultFactoryAdapter(
            w3=w3, address=settings.VAULT_FACTORY_ADDRESS
        )

        return cls(w3=w3, registry=registry, factory=factory)

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

    def build_register_strategy_tx(
        self,
        *,
        admin_wallet: str,
        adapter: str,
        dex_router: str,
        token0: str,
        token1: str,
        name: str,
        description: str,
    ) -> dict:
        return self.registry.build_register_strategy_tx(
            admin_wallet=admin_wallet,
            adapter=adapter,
            dex_router=dex_router,
            token0=token0,
            token1=token1,
            name=name,
            description=description,
        )

    def build_update_strategy_tx(
        self,
        *,
        admin_wallet: str,
        strategy_id: int,
        adapter: str,
        dex_router: str,
        token0: str,
        token1: str,
        name: str,
        description: str,
    ) -> dict:
        return self.registry.build_update_strategy_tx(
            admin_wallet=admin_wallet,
            strategy_id=strategy_id,
            adapter=adapter,
            dex_router=dex_router,
            token0=token0,
            token1=token1,
            name=name,
            description=description,
        )

    def build_set_strategy_active_tx(
        self,
        *,
        admin_wallet: str,
        strategy_id: int,
        active: bool,
    ) -> dict:
        return self.registry.build_set_strategy_active_tx(
            admin_wallet=admin_wallet,
            strategy_id=strategy_id,
            active=active,
        )

    # ------------------------------------------------------------------ #
    # Factory - views
    # ------------------------------------------------------------------ #

    def get_factory_config(self) -> dict:
        return self.factory.get_config()

    # ------------------------------------------------------------------ #
    # Factory - user tx
    # ------------------------------------------------------------------ #

    def build_create_vault_tx(self, strategy_id: int, user_wallet: str) -> dict:
        if not self.registry.is_strategy_active(strategy_id):
            raise ValueError("Strategy not active or does not exist on-chain")

        tx = self.factory.build_create_client_vault_tx(
            strategy_id=strategy_id,
            user_wallet=user_wallet,
        )
        return tx

    # ------------------------------------------------------------------ #
    # Factory - admin tx
    # ------------------------------------------------------------------ #

    def build_set_executor_tx(
        self,
        *,
        admin_wallet: str,
        new_executor: str,
    ) -> dict:
        return self.factory.build_set_executor_tx(
            admin_wallet=admin_wallet,
            new_executor=new_executor,
        )

    def build_set_fee_collector_tx(
        self,
        *,
        admin_wallet: str,
        new_collector: str,
    ) -> dict:
        return self.factory.build_set_fee_collector_tx(
            admin_wallet=admin_wallet,
            new_collector=new_collector,
        )

    def build_set_defaults_tx(
        self,
        *,
        admin_wallet: str,
        cooldown_sec: int,
        max_slippage_bps: int,
        allow_swap: bool,
    ) -> dict:
        return self.factory.build_set_defaults_tx(
            admin_wallet=admin_wallet,
            cooldown_sec=cooldown_sec,
            max_slippage_bps=max_slippage_bps,
            allow_swap=allow_swap,
        )
