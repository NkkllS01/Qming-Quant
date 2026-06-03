from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from storage.live_repository import LiveStateRepository
from storage.safety_repository import EquityRiskState, SafetyRepository


@dataclass(frozen=True)
class LiveEquityRiskResult:
    status: str
    reason: str
    currency: str
    equity: Decimal
    daily_equity_baseline: Decimal
    peak_equity: Decimal
    daily_loss_ratio: Decimal
    drawdown_ratio: Decimal

    @property
    def trading_allowed(self) -> bool:
        return self.status == "allowed"


class LiveEquityRiskGuard:
    def __init__(
        self,
        *,
        live_state_repository: LiveStateRepository,
        safety_repository: SafetyRepository,
        account_id: str,
        currency: str = "USDT",
        max_daily_loss: Decimal = Decimal("0.03"),
        max_total_drawdown: Decimal = Decimal("0.08"),
    ) -> None:
        self.live_state_repository = live_state_repository
        self.safety_repository = safety_repository
        self.account_id = account_id
        self.currency = currency
        self.max_daily_loss = max_daily_loss
        self.max_total_drawdown = max_total_drawdown

    def evaluate(self, *, now: datetime | None = None) -> LiveEquityRiskResult:
        now = now or datetime.now(timezone.utc)
        store = self.live_state_repository.load_snapshot(account_id=self.account_id)
        balance = store.balances.get(self.currency)
        if balance is None:
            return _result(
                status="blocked",
                reason="missing_equity_snapshot",
                currency=self.currency,
                equity=Decimal("0"),
                daily_equity_baseline=Decimal("0"),
                peak_equity=Decimal("0"),
            )
        if balance.equity <= 0:
            return _result(
                status="blocked",
                reason="invalid_equity_snapshot",
                currency=self.currency,
                equity=balance.equity,
                daily_equity_baseline=Decimal("0"),
                peak_equity=Decimal("0"),
            )

        state = self._refresh_state(balance.equity, now=now)
        daily_loss_ratio = _loss_ratio(state.daily_equity_baseline, balance.equity)
        drawdown_ratio = _loss_ratio(state.peak_equity, balance.equity)
        if daily_loss_ratio >= self.max_daily_loss:
            status = "blocked"
            reason = "daily_loss_limit_reached"
        elif drawdown_ratio >= self.max_total_drawdown:
            status = "blocked"
            reason = "drawdown_limit_reached"
        else:
            status = "allowed"
            reason = "within_equity_limits"
        return LiveEquityRiskResult(
            status=status,
            reason=reason,
            currency=self.currency,
            equity=balance.equity,
            daily_equity_baseline=state.daily_equity_baseline,
            peak_equity=state.peak_equity,
            daily_loss_ratio=daily_loss_ratio,
            drawdown_ratio=drawdown_ratio,
        )

    def _refresh_state(self, equity: Decimal, *, now: datetime) -> EquityRiskState:
        day = now.date().isoformat()
        state = self.safety_repository.get_equity_risk_state(
            account_id=self.account_id,
            currency=self.currency,
        )
        if state is None or state.day != day:
            refreshed = EquityRiskState(
                account_id=self.account_id,
                currency=self.currency,
                day=day,
                daily_equity_baseline=equity,
                peak_equity=equity,
                updated_at=now,
            )
        else:
            refreshed = EquityRiskState(
                account_id=self.account_id,
                currency=self.currency,
                day=state.day,
                daily_equity_baseline=state.daily_equity_baseline,
                peak_equity=max(state.peak_equity, equity),
                updated_at=now,
            )
        return self.safety_repository.upsert_equity_risk_state(refreshed)


def _loss_ratio(reference: Decimal, current: Decimal) -> Decimal:
    if reference <= 0 or current >= reference:
        return Decimal("0")
    return (reference - current) / reference


def _result(
    *,
    status: str,
    reason: str,
    currency: str,
    equity: Decimal,
    daily_equity_baseline: Decimal,
    peak_equity: Decimal,
) -> LiveEquityRiskResult:
    return LiveEquityRiskResult(
        status=status,
        reason=reason,
        currency=currency,
        equity=equity,
        daily_equity_baseline=daily_equity_baseline,
        peak_equity=peak_equity,
        daily_loss_ratio=Decimal("0"),
        drawdown_ratio=Decimal("0"),
    )
