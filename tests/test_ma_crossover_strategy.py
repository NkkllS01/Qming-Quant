from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.models import Candle
from strategies.examples.ma_crossover import MovingAverageCrossoverStrategy


def test_ma_crossover_emits_long_open_signal_on_bullish_cross() -> None:
    strategy = _strategy()
    candles = _candles([10, 10, 10, 10, 10, 14])

    signals = strategy.on_candles({}, candles)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.action == "open"
    assert signal.direction == "long"
    assert signal.reason == "fast SMA crossed above slow SMA"
    assert signal.stop_loss_pct == 0.02
    assert signal.take_profit_pct == 0.04


def test_ma_crossover_emits_no_signal_before_warmup() -> None:
    strategy = _strategy()

    assert strategy.on_candles({}, _candles([10, 11, 12, 13])) == []


def test_ma_crossover_emits_no_signal_without_cross() -> None:
    strategy = _strategy()

    assert strategy.on_candles({}, _candles([10, 10, 10, 10, 10, 10])) == []


def test_ma_crossover_filters_symbol_timeframe_and_unconfirmed_candles() -> None:
    strategy = _strategy()
    candles = _candles([10, 10, 10, 10, 10, 14])
    candles[-1] = candles[-1].model_copy(update={"confirmed": False})
    candles.append(candles[-1].model_copy(update={"symbol": "ETH-USDT-SWAP", "confirmed": True}))
    candles.append(candles[-1].model_copy(update={"timeframe": "1h", "confirmed": True}))

    assert strategy.on_candles({}, candles) == []


def _strategy() -> MovingAverageCrossoverStrategy:
    return MovingAverageCrossoverStrategy(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_ma_crossover_15m",
        symbol="BTC-USDT-SWAP",
        run_id="test-run",
        timeframe="15m",
        fast_period=2,
        slow_period=5,
    )


def _candles(closes: list[int]) -> list[Candle]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        Candle(
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            timestamp=start + timedelta(minutes=15 * idx),
            open=Decimal(close),
            high=Decimal(close + 1),
            low=Decimal(close - 1),
            close=Decimal(close),
            volume=Decimal("100"),
            confirmed=True,
        )
        for idx, close in enumerate(closes)
    ]
