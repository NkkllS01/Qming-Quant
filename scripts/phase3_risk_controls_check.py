from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.models import Candle
from paper.engine import PaperTradingEngine
from strategies.examples.ma_crossover import MovingAverageCrossoverStrategy


def main() -> None:
    try:
        _run_check()
    except Exception as exc:
        print(f"FAIL phase3 risk controls check: {exc}")
        raise SystemExit(1) from exc
    print("PASS phase3 risk controls check")


def _run_check() -> None:
    _check_position_size_cap()
    _check_open_position_limit_rejects_signal()
    _check_daily_loss_limit()
    _check_drawdown_pause()


def _check_position_size_cap() -> None:
    strategy = _strategy("risk-size-cap")
    result = PaperTradingEngine(initial_equity=Decimal("1000"), default_size=Decimal("100")).run(
        strategy,
        _ma_crossover_candles("BTC-USDT-SWAP"),
    )
    if not result.fills:
        raise RuntimeError("position size cap check produced no fill")
    if result.fills[0].size >= Decimal("100"):
        raise RuntimeError(f"fill size was not risk-capped: {result.fills[0].size}")


def _check_open_position_limit_rejects_signal() -> None:
    strategy = _strategy("risk-open-limit")
    result = PaperTradingEngine(
        initial_equity=Decimal("1000"),
        default_size=Decimal("1"),
        max_open_positions=0,
    ).run(strategy, _ma_crossover_candles("BTC-USDT-SWAP"))
    if result.fills_count != 0 or result.approved_count != 0:
        raise RuntimeError("open position limit allowed a trade")
    if not any(event.event_type == "risk_rejected" for event in result.journal):
        raise RuntimeError("open position limit did not record a risk rejection")


def _check_daily_loss_limit() -> None:
    result = PaperTradingEngine(
        initial_equity=Decimal("1000"),
        current_daily_loss=Decimal("30"),
    ).run(_strategy("risk-daily-loss"), _ma_crossover_candles("BTC-USDT-SWAP"))
    _assert_risk_rejected(result, "daily loss limit reached")


def _check_drawdown_pause() -> None:
    result = PaperTradingEngine(
        initial_equity=Decimal("1000"),
        current_drawdown=Decimal("0.08"),
    ).run(_strategy("risk-drawdown"), _ma_crossover_candles("BTC-USDT-SWAP"))
    _assert_risk_rejected(result, "drawdown pause reached")


def _assert_risk_rejected(result, reason: str) -> None:
    if result.fills_count != 0 or result.approved_count != 0:
        raise RuntimeError(f"{reason} allowed a trade")
    if not result.journal or result.journal[-1].message != reason:
        raise RuntimeError(f"{reason} did not record the expected rejection")


def _strategy(run_id: str) -> MovingAverageCrossoverStrategy:
    return MovingAverageCrossoverStrategy(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_ma_crossover_15m",
        symbol="BTC-USDT-SWAP",
        run_id=run_id,
        timeframe="15m",
    )


def _ma_crossover_candles(symbol: str) -> list[Candle]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    closes = [Decimal("100") for _ in range(28)] + [Decimal("101"), Decimal("102")]
    return [
        Candle(
            symbol=symbol,
            timeframe="15m",
            timestamp=start + timedelta(minutes=15 * index),
            open=close,
            high=close + Decimal("1"),
            low=close - Decimal("1"),
            close=close,
            volume=Decimal("100"),
            confirmed=True,
        )
        for index, close in enumerate(closes)
    ]


if __name__ == "__main__":
    main()
