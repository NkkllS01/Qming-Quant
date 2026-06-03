from decimal import Decimal

from core.models import Signal
from risk.manager import PortfolioRiskManager


def _signal(
    *,
    action: str = "open",
    symbol: str = "BTC-USDT-SWAP",
    stop_loss_pct: float | None = 0.01,
) -> Signal:
    return Signal(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol=symbol,
        run_id="run-1",
        action=action,
        direction="long",
        confidence=0.8,
        timeframe="15m",
        reason="test",
        stop_loss_pct=stop_loss_pct,
    )


def test_risk_manager_requires_stop_loss_for_open_signal() -> None:
    manager = PortfolioRiskManager()

    decision = manager.evaluate(
        _signal(stop_loss_pct=None),
        equity=Decimal("1000"),
        open_positions=0,
        entry_price=Decimal("100"),
    )

    assert decision.approved is False
    assert "stop loss" in decision.reason


def test_risk_manager_sizes_position_from_risk_budget_and_stop_distance() -> None:
    manager = PortfolioRiskManager(max_risk_per_trade=Decimal("0.005"))

    decision = manager.evaluate(
        _signal(stop_loss_pct=0.01),
        equity=Decimal("1000"),
        open_positions=0,
        entry_price=Decimal("100"),
    )

    assert decision.approved is True
    assert decision.max_loss_usdt == Decimal("5.00")
    assert decision.adjusted_size == Decimal("5")


def test_risk_manager_rejects_when_daily_loss_limit_reached() -> None:
    manager = PortfolioRiskManager(max_daily_loss=Decimal("0.03"))

    decision = manager.evaluate(
        _signal(),
        equity=Decimal("1000"),
        open_positions=0,
        entry_price=Decimal("100"),
        current_daily_loss=Decimal("30"),
    )

    assert decision.approved is False
    assert "daily loss" in decision.reason


def test_risk_manager_rejects_when_drawdown_pause_reached() -> None:
    manager = PortfolioRiskManager(max_total_drawdown_pause=Decimal("0.08"))

    decision = manager.evaluate(
        _signal(),
        equity=Decimal("1000"),
        open_positions=0,
        entry_price=Decimal("100"),
        current_drawdown=Decimal("0.08"),
    )

    assert decision.approved is False
    assert "drawdown" in decision.reason


def test_risk_manager_rejects_duplicate_open_symbol() -> None:
    manager = PortfolioRiskManager()

    decision = manager.evaluate(
        _signal(symbol="BTC-USDT-SWAP"),
        equity=Decimal("1000"),
        open_positions=1,
        entry_price=Decimal("100"),
        open_symbols={"BTC-USDT-SWAP"},
    )

    assert decision.approved is False
    assert "already open" in decision.reason


def test_risk_manager_allows_close_without_entry_price_or_stop_loss() -> None:
    manager = PortfolioRiskManager()

    decision = manager.evaluate(
        _signal(action="close", stop_loss_pct=None),
        equity=Decimal("1000"),
        open_positions=1,
    )

    assert decision.approved is True
