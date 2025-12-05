# adapters/entry/http/vaults_batch_router.py

from fastapi import APIRouter, Depends

from core.domain.pancake_batch_request import PancakeBatchRequest
from core.use_cases.vaults_batch_usecase import VaultsBatchUseCase



router = APIRouter(prefix="/vaults", tags=["vaults-batch"])


def get_vaults_batch_use_case(
) -> VaultsBatchUseCase:
    """
    Dependency factory for wiring VaultsBatchUseCase.

    This function centralizes the construction of the use case so all batch
    endpoints share the same repository instances and state tracking.
    """
    return VaultsBatchUseCase()


@router.post("/pancake/{alias}/batch/unstake-exit-swap-open")
def pancake_batch_unstake_exit_swap_open_view(
    alias: str,
    req: PancakeBatchRequest,
    use_case: VaultsBatchUseCase = Depends(get_vaults_batch_use_case),
):
    """
    HTTP endpoint for the full Pancake batch operation:

      1) Unstake from gauge.
      2) Exit current position to idle balances.
      3) Optionally perform an exact-in swap.
      4) Open a new position with the resulting balance and range.

    All business logic is delegated to `VaultsBatchUseCase`, and the call is
    executed atomically via the vault contract.

    Returns:
        A dictionary with transaction details, gas usage, snapshots and the
        effective range used.
    """
    return use_case.pancake_batch_unstake_exit_swap_open(alias, req)
