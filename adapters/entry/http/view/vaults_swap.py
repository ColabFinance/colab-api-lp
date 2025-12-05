# adapters/entry/http/vaults_swap_router.py

from fastapi import APIRouter, Depends

from core.domain.swap import SwapExactInRequest, SwapQuoteRequest
from core.use_cases.vaults_swap_usecase import VaultsSwapUseCase


router = APIRouter(prefix="/vaults", tags=["vaults-swap"])


def get_vaults_swap_use_case(
) -> VaultsSwapUseCase:
    """
    Dependency factory that wires the VaultsSwapUseCase with the concrete
    vault registry repository and state repository.

    This keeps the router thin and focused on HTTP concerns only.
    """
    return VaultsSwapUseCase()


@router.post("/uniswap/{alias}/swap/quote")
def uniswap_swap_quote_view(
    alias: str,
    req: SwapQuoteRequest,
    use_case: VaultsSwapUseCase = Depends(get_vaults_swap_use_case),
):
    """
    HTTP endpoint that proxies to `VaultsSwapUseCase.uniswap_swap_quote`.

    Args:
        alias: Human-friendly alias of the vault.
        req: SwapQuoteRequest payload.

    Returns:
        A detailed quote for an exact-in swap on Uniswap v3.
    """
    return use_case.uniswap_swap_quote(alias, req)


@router.post("/uniswap/{alias}/swap/exact-in")
def uniswap_swap_exact_in_view(
    alias: str,
    req: SwapExactInRequest,
    use_case: VaultsSwapUseCase = Depends(get_vaults_swap_use_case),
):
    """
    HTTP endpoint that proxies to `VaultsSwapUseCase.uniswap_swap_exact_in`.

    Executes an exact-in swap using the vault as the trading account and
    returns gas and balance information.
    """
    return use_case.uniswap_swap_exact_in(alias, req)


@router.post("/aerodrome/{alias}/swap/quote")
def aerodrome_swap_quote_view(
    alias: str,
    req: SwapQuoteRequest,
    use_case: VaultsSwapUseCase = Depends(get_vaults_swap_use_case),
):
    """
    HTTP endpoint for Aerodrome quote, delegating to the swap use case.

    Returns:
        A quote using Aerodrome's tickSpacing logic and quoter.
    """
    return use_case.aerodrome_swap_quote(alias, req)


@router.post("/aerodrome/{alias}/swap/exact-in")
def aerodrome_swap_exact_in_view(
    alias: str,
    req: SwapExactInRequest,
    use_case: VaultsSwapUseCase = Depends(get_vaults_swap_use_case),
):
    """
    HTTP endpoint for Aerodrome exact-in swap.

    Executes the full on-chain swap and returns execution information.
    """
    return use_case.aerodrome_swap_exact_in(alias, req)


@router.post("/pancake/{alias}/swap/quote")
def pancake_swap_quote_view(
    alias: str,
    req: SwapQuoteRequest,
    use_case: VaultsSwapUseCase = Depends(get_vaults_swap_use_case),
):
    """
    HTTP endpoint for Pancake v3 quote.

    Returns:
        Best fee tier and detailed gas/value estimates for an exact-in swap.
    """
    return use_case.pancake_swap_quote(alias, req)


@router.post("/pancake/{alias}/swap/exact-in")
def pancake_swap_exact_in_view(
    alias: str,
    req: SwapExactInRequest,
    use_case: VaultsSwapUseCase = Depends(get_vaults_swap_use_case),
):
    """
    HTTP endpoint for Pancake v3 exact-in swap.

    Delegates all business logic to `VaultsSwapUseCase.pancake_swap_exact_in`.
    """
    return use_case.pancake_swap_exact_in(alias, req)
