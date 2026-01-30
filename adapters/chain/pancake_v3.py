# apps/api/adapters/pancake_v3.py
import os
from typing import Dict, Any, Tuple, Optional
from web3 import Web3

from adapters.chain.artifacts import load_abi_json, load_abi_from_out
from .base import DexAdapter
from adapters.chain.utils import get_sqrt_ratio_at_tick, get_amounts_for_liquidity
from config import get_settings


U128_MAX = (1<<128) - 1


class PancakeV3Adapter(DexAdapter):
    """Adapter para PancakeSwap v3 (Uniswap v3-like) + MasterChefV3 farms."""

    def pool_abi(self) -> list:         return load_abi_json("pancake","Pool.json")
    def nfpm_abi(self) -> list:         return load_abi_json("pancake","NonfungiblePositionManager.json")
    def erc20_abi(self) -> list:        return load_abi_from_out("common","ERC20.json")
    def quoter_abi(self) -> list:       return load_abi_json("pancake","QuoterV2.json")
    def masterchef_abi(self) -> list:   return load_abi_json("pancake","MasterChefV3.json")

    # ---------- contratos ----------
    def pool_contract(self):
        return self.w3.eth.contract(address=Web3.to_checksum_address(self.pool), abi=self.pool_abi())

    def nfpm_contract(self):
        return self.w3.eth.contract(address=Web3.to_checksum_address(self.nfpm), abi=self.nfpm_abi()) if self.nfpm else None

    def quoter(self, addr: str):
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=self.quoter_abi())

    def masterchef(self, addr: str):
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=self.masterchef_abi())

    # --- helpers de gauge (MasterChefV3) ---
    def gauge_contract(self):
        ga = self.gauge
        return self.masterchef(ga) if ga else None

    def adapter_address(self) -> str:
        """
        Return the on-chain CL adapter address wired in the ClientVault.

        This is used by some gauges (Aero-style) that require the adapter
        as an argument for reward accounting.
        """
        try:
            return self.vault.functions.adapter().call()
        except Exception:
            # Fallback: keep old behavior if needed
            return self.pool

    # ---------- leituras ----------
    def slot0(self) -> Tuple[int,int]:
        s = self.pool_contract().functions.slot0().call()
        return int(s[0]), int(s[1])

    def observe_twap_tick(self, window: int) -> int:
        tick_cums, _ = self.pool_contract().functions.observe([window, 0]).call()
        return (int(tick_cums[1]) - int(tick_cums[0])) // int(window)

    def pool_meta(self) -> Dict[str, Any]:
        pc = self.pool_contract()
        t0 = pc.functions.token0().call()
        t1 = pc.functions.token1().call()
        e0 = self.erc20(t0); e1 = self.erc20(t1)
        try: sym0 = e0.functions.symbol().call()
        except: sym0 = "T0"
        try: sym1 = e1.functions.symbol().call()
        except: sym1 = "T1"
        dec0 = int(e0.functions.decimals().call())
        dec1 = int(e1.functions.decimals().call())
        # fee() existe no Pancake v3 pool (Uniswap-like)
        fee = int(pc.functions.fee().call())
        tickSpacing = int(pc.functions.tickSpacing().call())
        return {"token0": t0, "token1": t1, "sym0": sym0, "sym1": sym1, "dec0": dec0, "dec1": dec1, "fee": fee, "spacing": tickSpacing}

    def vault_state(self) -> Dict[str, Any]:
        """
        Read current position state from ClientVault + NFPM.

        Returns a dict compatible with status_service.compute_status:
        {
          "tokenId": uint256,
          "lower": int24,
          "upper": int24,
          "liq": uint128,
          "staked": bool,
          "gauge": address|None,
          "twapOk": bool,
          "lastRebalance": uint256,   # unix timestamp
          "min_cd": uint256           # cooldown in seconds
        }
        """
        # --- tokenId from ClientVault
        token_id = 0
        try:
            token_id = int(self.vault.functions.positionTokenId().call())
        except Exception:
            try:
                token_id = int(self.vault.functions.positionTokenIdView().call())
            except Exception:
                token_id = 0

        lower = upper = 0
        liq = 0
        if token_id:
            nfpm = self.nfpm_contract()
            (_n, _op, _t0, _t1, _fee, l, u, L, *_rest) = nfpm.functions.positions(int(token_id)).call()
            lower, upper, liq = int(l), int(u), int(L)
        else:
            # No position: use spot tick just for reference
            _, spot_tick = self.slot0()
            lower = upper = int(spot_tick)
            liq = 0

        # --- staking flag: NFT owner is gauge when staked
        mcv3_addr = self.gauge
        staked = False
        if token_id and mcv3_addr:
            try:
                owner = self.nfpm_contract().functions.ownerOf(int(token_id)).call()
                staked = owner.lower() == mcv3_addr.lower()
            except Exception:
                staked = False

        # --- cooldown / lastRebalance from ClientVault
        try:
            last_reb = int(self.vault.functions.lastRebalanceTs().call())
        except Exception:
            last_reb = 0

        try:
            cooldown_sec = int(self.vault.functions.cooldownSec().call())
        except Exception:
            cooldown_sec = 0

        return {
            "tokenId": token_id,
            "lower": lower,
            "upper": upper,
            "liq": liq,
            "staked": staked,
            "gauge": (mcv3_addr if mcv3_addr else None),
            "twapOk": True,          # ClientVault no longer enforces TWAP on-chain
            "lastRebalance": last_reb,
            "min_cd": cooldown_sec,  # kept as "min_cd" for status_service compatibility
        }
        
    def amounts_in_position_now(self, lower: int, upper: int, liq: int) -> Tuple[int,int]:
        sqrtP = self.slot0()[0]
        sqrtA = get_sqrt_ratio_at_tick(lower)
        sqrtB = get_sqrt_ratio_at_tick(upper)
        return get_amounts_for_liquidity(sqrtP, sqrtA, sqrtB, liq)

    def call_static_collect(self, token_id: int, recipient: str) -> Tuple[int, int]:
        if not self.nfpm or not token_id:
            return (0, 0)
        nfpm = self.nfpm_contract()
        a0, a1 = nfpm.functions.collect((int(token_id), Web3.to_checksum_address(recipient), U128_MAX, U128_MAX)).call()
        return int(a0), int(a1)

    # ---------- helpers MasterChef ----------
    def masterchef_pid_for_pool(self, masterchef_addr: str, pool_addr: str) -> Optional[int]:
        try:
            mc = self.masterchef(masterchef_addr)
            pid = int(mc.functions.v3PoolAddressPid(Web3.to_checksum_address(pool_addr)).call())
            return pid if pid != 0 else None
        except Exception:
            return None

    def masterchef_pending(self, masterchef_addr: str, token_id: int) -> int:
        try:
            mc = self.masterchef(masterchef_addr)
            return int(mc.functions.pendingCake(int(token_id)).call())
        except Exception:
            return 0

    # ---------- swaps no Vault (Pancake v3 ≈ Uniswap v3) ----------
    def fn_vault_swap_exact_in(self, router: str, token_in: str, token_out: str,
                               fee: int, amount_in_raw: int, min_out_raw: int,
                               sqrt_price_limit_x96: int = 0):
        """
        Build a tx for a vault-level exactInputSingle swap.

        NOTE: The new ClientVault does NOT expose this function. This helper
        is kept only for legacy vaults that still implement _swapExactInPancake.
        """
        if not hasattr(self.vault.functions, "swapExactInPancake"):
            raise NotImplementedError("Vault missing swapExactInPancake (ClientVault does not expose direct swaps).")

        return self.vault.functions.swapExactInPancake(
            Web3.to_checksum_address(router),
            Web3.to_checksum_address(token_in),
            Web3.to_checksum_address(token_out),
            int(fee),
            int(amount_in_raw),
            int(min_out_raw),
            int(sqrt_price_limit_x96 or 0),
        )

    def fn_batch_unstake_exit_swap_open_pancake(
        self,
        router: str,
        token_in: str,
        token_out: str,
        fee: int,
        amount_in_raw: int,
        min_out_raw: int,
        sqrt_price_limit_x96: int,
        lower_tick: int,
        upper_tick: int,
    ):
        """
        Build tx for vault.unstakeExitSwapAndOpenPancake(...).
        """
        if hasattr(self.vault.functions, "unstakeExitSwapAndOpenPancake"):
            return self.vault.functions.unstakeExitSwapAndOpenPancake(
                Web3.to_checksum_address(router),
                Web3.to_checksum_address(token_in),
                Web3.to_checksum_address(token_out),
                int(fee),
                int(amount_in_raw),
                int(min_out_raw),
                int(sqrt_price_limit_x96 or 0),
                int(lower_tick),
                int(upper_tick),
            )
        raise NotImplementedError("Vault missing unstakeExitSwapAndOpenPancake")
    
    # ---------- farms (MasterChefV3) ----------
    def fn_stake(self):
        """Stake via Vault.stake() -> adapter.stakePosition(gauge)."""
        if hasattr(self.vault.functions, "stake"):
            return self.vault.functions.stake()
        raise NotImplementedError("Vault must implement stake().")

    def fn_unstake(self):
        """Unstake via Vault.unstake() -> adapter.unstakePosition(gauge)."""
        if hasattr(self.vault.functions, "unstake"):
            return self.vault.functions.unstake()
        raise NotImplementedError("Vault must implement unstake().")

    def fn_harvest(self):
        """Harvest via Vault.claimRewards() -> adapter.claimRewards(gauge)."""
        if hasattr(self.vault.functions, "claimRewards"):
            return self.vault.functions.claimRewards()
        raise NotImplementedError("Vault must implement claimRewards().")
