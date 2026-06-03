from __future__ import annotations

from dataclasses import dataclass

from live.reconcile import LiveReconciliationService, LiveReconcileResult
from live.risk import LiveEquityRiskGuard, LiveEquityRiskResult
from storage.safety_repository import PauseState, SafetyRepository


@dataclass(frozen=True)
class TradingGateResult:
    status: str
    reason: str
    pause_state: PauseState
    reconciliation: LiveReconcileResult | None = None
    equity_risk: LiveEquityRiskResult | None = None

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
        equity_risk_guard: LiveEquityRiskGuard | None = None,
    ) -> None:
        self.reconciliation = reconciliation
        self.safety_repository = safety_repository
        self.account_id = account_id
        self.equity_risk_guard = equity_risk_guard

    def evaluate(self) -> TradingGateResult:
        pause_state = self.safety_repository.get_pause(account_id=self.account_id)
        if pause_state.paused:
            return TradingGateResult(
                status="blocked",
                reason="manual_pause",
                pause_state=pause_state,
            )

        equity_risk = None
        if self.equity_risk_guard is not None:
            equity_risk = self.equity_risk_guard.evaluate()
            if not equity_risk.trading_allowed:
                return TradingGateResult(
                    status="blocked",
                    reason=equity_risk.reason,
                    pause_state=pause_state,
                    equity_risk=equity_risk,
                )

        reconciliation = self.reconciliation.run()
        if not reconciliation.is_clean:
            return TradingGateResult(
                status="blocked",
                reason="reconciliation_blocked",
                pause_state=pause_state,
                reconciliation=reconciliation,
                equity_risk=equity_risk,
            )

        return TradingGateResult(
            status="allowed",
            reason="all_checks_passed",
            pause_state=pause_state,
            reconciliation=reconciliation,
            equity_risk=equity_risk,
        )
