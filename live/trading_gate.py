from __future__ import annotations

from dataclasses import dataclass

from live.reconcile import LiveReconciliationService, LiveReconcileResult
from storage.safety_repository import PauseState, SafetyRepository


@dataclass(frozen=True)
class TradingGateResult:
    status: str
    reason: str
    pause_state: PauseState
    reconciliation: LiveReconcileResult | None = None

    @property
    def trading_allowed(self) -> bool:
        return self.status == "allowed"


class TradingGateService:
    def __init__(
        self,
        *,
        reconciliation: LiveReconciliationService,
        safety_repository: SafetyRepository,
        account_id: str,
    ) -> None:
        self.reconciliation = reconciliation
        self.safety_repository = safety_repository
        self.account_id = account_id

    def evaluate(self) -> TradingGateResult:
        pause_state = self.safety_repository.get_pause(account_id=self.account_id)
        if pause_state.paused:
            return TradingGateResult(
                status="blocked",
                reason="manual_pause",
                pause_state=pause_state,
            )

        reconciliation = self.reconciliation.run()
        if not reconciliation.is_clean:
            return TradingGateResult(
                status="blocked",
                reason="reconciliation_blocked",
                pause_state=pause_state,
                reconciliation=reconciliation,
            )

        return TradingGateResult(
            status="allowed",
            reason="all_checks_passed",
            pause_state=pause_state,
            reconciliation=reconciliation,
        )
