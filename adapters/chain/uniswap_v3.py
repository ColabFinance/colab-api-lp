from typing import Dict, Any, Tuple, Optional
from web3 import Web3

from adapters.chain.artifacts import load_abi_json, load_abi_from_out
from .base import DexAdapter
from adapters.chain.utils import get_sqrt_ratio_at_tick, get_amounts_for_liquidity


U128_MAX = (1<<128) - 1

class UniswapV3Adapter(DexAdapter):
    """Concrete adapter for Uniswap v3 + SingleUserVault."""

    def pool_contract(self):
        return self.w3.eth.contract(address=Web3.to_checksum_address(self.pool), abi=load_abi_json("uniswap", "Pool.min.json"))

    def nfpm_contract(self):
        return self.w3.eth.contract(address=Web3.to_checksum_address(self.nfpm), abi=load_abi_json("uniswap", "NFPM.min.json")) if self.nfpm else None

    def quoter(self, addr: str):
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=load_abi_json("uniswap", "QuoterV2.min.json"))
    
    # ---------- reads ----------
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
        spacing = int(pc.functions.tickSpacing().call())
        e0 = self.erc20(t0)
        e1 = self.erc20(t1)
        sym0 = e0.functions.symbol().call()
        sym1 = e1.functions.symbol().call()
        dec0 = int(e0.functions.decimals().call())
        dec1 = int(e1.functions.decimals().call())
        return {"token0": t0, "token1": t1, "spacing": spacing, "sym0": sym0, "sym1": sym1, "dec0": dec0, "dec1": dec1}

    def vault_state(self) -> Dict[str, Any]:
        # 1) tentar achar o adapter no vault (V2)
        adapter_addr = None
        try:
            # tentar ABI V2
            v2 = self.w3.eth.contract(address=self.vault.address, abi=load_abi_from_out("vaults", "ClientVault.json"))
            adapter_addr = v2.functions.adapter().call()
        except Exception:
            adapter_addr = None

        token_id = 0
        lower = upper = 0
        liq = 0
        twap_ok = True
        last_reb = 0
        pool_addr = Web3.to_checksum_address(self.pool)
        
        if adapter_addr and int(adapter_addr, 16) != 0:
            ac = self.w3.eth.contract(address=Web3.to_checksum_address(adapter_addr), abi=load_abi_from_out("vaults", "UniV3Adapter.json"))
            # tokenId (NFT está no adapter)
            try:
                token_id = int(ac.functions.currentTokenId(self.vault.address).call())
            except Exception:
                token_id = 0
            # range + liq
            if token_id != 0:
                try:
                    l,u,L = ac.functions.currentRange(self.vault.address).call()
                    lower, upper, liq = int(l), int(u), int(L)
                except Exception:
                    lower = upper = self.slot0()[1]; liq = 0
            else:
                lower = upper = self.slot0()[1]; liq = 0
                
            # twap e lastRebalance
            try:
                twap_ok = bool(ac.functions.twapOk().call())
            except Exception:
                twap_ok = True
            try:
                last_reb = int(ac.functions.lastRebalance(self.vault.address).call())
            except Exception:
                last_reb = 0

            try:
                min_cd = int(ac.functions.minCooldown().call())
            except Exception:
                min_cd = 0
                
            # pool/nfpm (se quiser sobrepor)
            try:
                pool_addr = ac.functions.pool().call()
            except Exception:
                pass
            
        return {
            "pool": pool_addr,
            "tokenId": token_id,
            "lower": lower,
            "upper": upper,
            "liq": liq,
            "twapOk": twap_ok,
            "lastRebalance": last_reb,
            "min_cd": min_cd
        }
            
    def amounts_in_position_now(self, lower: int, upper: int, liq: int) -> Tuple[int,int]:
        sqrtP = self.slot0()[0]
        sqrtA = get_sqrt_ratio_at_tick(lower)
        sqrtB = get_sqrt_ratio_at_tick(upper)
        return get_amounts_for_liquidity(sqrtP, sqrtA, sqrtB, liq)

    def call_static_collect(self, token_id: int, recipient: str) -> Tuple[int, int]:
        if not self.nfpm:
            return (0, 0)
        nfpm = self.nfpm_contract()
        a0, a1 = nfpm.functions.collect((token_id, Web3.to_checksum_address(recipient), U128_MAX, U128_MAX)).call()
        return int(a0), int(a1)

    def uni_pool_fee(self, pool_addr: str) -> int:
        pool = self.w3.eth.contract(
            address=Web3.to_checksum_address(pool_addr),
            abi=self.pool_abi(),
        )
        return int(pool.functions.fee().call())
    
    # ---------- writes (return ContractFunctions) ----------
    def fn_open(self, lower: int, upper: int):
        # adapt name if contract uses different selector
        if hasattr(self.vault.functions, "openInitialPosition"):
            return self.vault.functions.openInitialPosition(int(lower), int(upper))
        raise NotImplementedError("Vault missing openInitialPosition")

    def fn_rebalance_caps(self, lower: int, upper: int, cap0_raw: Optional[int], cap1_raw: Optional[int]):
        # give sane defaults if caps missing
        cap0_raw = int(cap0_raw or 0)
        cap1_raw = int(cap1_raw or 0)
        if hasattr(self.vault.functions, "rebalanceWithCaps"):
            return self.vault.functions.rebalanceWithCaps(int(lower), int(upper), int(cap0_raw), int(cap1_raw))
        raise NotImplementedError("Vault missing rebalanceWithCaps")

    def fn_exit(self):
        if hasattr(self.vault.functions, "exitPositionToVault"):
            return self.vault.functions.exitPositionToVault()
        raise NotImplementedError("Vault missing exitPositionToVault")

    def fn_exit_withdraw(self, to_addr: str):
        if hasattr(self.vault.functions, "exitPositionAndWithdrawAll"):
            return self.vault.functions.exitPositionAndWithdrawAll(Web3.to_checksum_address(to_addr))
        raise NotImplementedError("Vault missing exitPositionAndWithdrawAll")

    def fn_collect(self):
        if hasattr(self.vault.functions, "collectToVault"):
            return self.vault.functions.collectToVault()
        raise NotImplementedError("Vault missing collectToVault")

    def fn_deposit_erc20(self, token: str, amount_raw: int):
        # default simple transfer to vault address
        c = self.erc20(token)
        return c.functions.transfer(self.vault.address, int(amount_raw))

    def fn_deploy_vault(self, nfpm: str):
        # TODO: if have a factory, implement here
        raise NotImplementedError("Deployment via adapter not implemented (use factory when available).")

    def fn_vault_swap_exact_in(self, router: str, token_in: str, token_out: str,
                               fee: int, amount_in_raw: int,
                               min_out_raw: int, sqrt_price_limit_x96: int = 0):
        # chama a função do VaultV2
        return self.vault.functions.swapExactIn(
            Web3.to_checksum_address(router),
            Web3.to_checksum_address(token_in),
            Web3.to_checksum_address(token_out),
            int(fee),
            int(amount_in_raw),
            int(min_out_raw),
            int(sqrt_price_limit_x96)
        )
