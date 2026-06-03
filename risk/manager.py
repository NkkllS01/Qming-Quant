from __future__ import annotations

from decimal import Decimal

from core.models import RiskDecision, Signal


class PortfolioRiskManager:
    def __init__(
        self,
        *,
        max_risk_per_trade: Decimal = Decimal("0.005"),
        max_daily_loss: Decimal = Decimal("0.03"),
        max_total_drawdown_pause: Decimal = Decimal("0.08"),
        max_open_positions: int = 2,
        max_leverage: int = 3,
    ) -> None:
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_total_drawdown_pause = max_total_drawdown_pause
        self.max_open_positions = max_open_positions
        self.max_leverage = max_leverage

    def evaluate(
        self,
        signal: Signal,
        *,
        equity: Decimal,
        open_positions: int,
        entry_price: Decimal | None = None,
        current_daily_loss: Decimal = Decimal("0"),
        current_drawdown: Decimal = Decimal("0"),
        open_symbols: set[str] | None = None,
    ) -> RiskDecision:
        if signal.action != "open":
            return RiskDecision(
                approved=True,
                reason="close signal allowed",
                leverage=self.max_leverage,
            )
        if open_positions >= self.max_open_positions:
            return RiskDecision(
                approved=False,
                reason="open position limit reached",
                leverage=self.max_leverage,
            )
        if open_symbols is not None and signal.symbol in open_symbols:
            return RiskDecision(
                approved=False,
                reason="symbol already open",
                leverage=self.max_leverage,
            )
        if current_daily_loss >= equity * self.max_daily_loss:
            return RiskDecision(
                approved=False,
                reason="daily loss limit reached",
                leverage=self.max_leverage,
            )
        if current_drawdown >= self.max_total_drawdown_pause:
            return RiskDecision(
                approved=False,
                reason="drawdown pause reached",
                leverage=self.max_leverage,
            )
        if signal.stop_loss_pct is None or signal.stop_loss_pct <= 0:
            return RiskDecision(
                approved=False,
                reason="open signal requires stop loss",
                leverage=self.max_leverage,
            )
        if entry_price is None or entry_price <= 0:
            return RiskDecision(
                approved=False,
                reason="open signal requires valid entry price",
                leverage=self.max_leverage,
            )
        max_loss = (equity * self.max_risk_per_trade).quantize(Decimal("0.01"))
        stop_distance = entry_price * Decimal(str(signal.stop_loss_pct))
        if stop_distance <= 0:
            return RiskDecision(
                approved=False,
                reason="open signal requires valid stop distance",
                leverage=self.max_leverage,
            )
        adjusted_size = max_loss / stop_distance
        return RiskDecision(
            approved=True,
            reason="within risk limits",
            original_size=adjusted_size,
            adjusted_size=adjusted_size.normalize(),
            max_loss_usdt=max_loss,
            leverage=self.max_leverage,
        )
