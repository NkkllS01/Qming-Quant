from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.models import Candle
from strategies.examples.channel_breakout import AtrChannelBreakoutStrategy


def _strategy(**overrides: object) -> AtrChannelBreakoutStrategy:
    params = {
        "account_id": "okx_sub_main",
        "bot_id": "okx_perp_bot_main",
        "strategy_id": "btc_channel_breakout_15m",
        "symbol": "BTC-USDT-SWAP",
        "run_id": "run-1",
        "lookback": 3,
        "atr_period": 2,
        "atr_multiplier": 2,
        "reward_risk": 3,
        "min_atr_pct": 0.001,
        "max_atr_pct": 0.08,
    }
    params.update(overrides)
    return AtrChannelBreakoutStrategy(**params)


def _candle(
    index: int,
    *,
    symbol: str = "BTC-USDT-SWAP",
    close: str = "100",
    high: str | None = None,
    low: str | None = None,
    open_: str | None = None,
    timeframe: str = "15m",
    confirmed: bool = True,
) -> Candle:
    close_value = Decimal(close)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * index),
        open=Decimal(open_) if open_ is not None else close_value,
        high=Decimal(high) if high is not None else close_value + Decimal("1"),
        low=Decimal(low) if low is not None else close_value - Decimal("1"),
        close=close_value,
        volume=Decimal("100"),
        confirmed=confirmed,
    )


def _breakout_candles() -> list[Candle]:
    return [
        _candle(0, open_="98", high="101", low="97", close="100"),
        _candle(1, open_="100", high="106", low="98", close="104"),
        _candle(2, high="111", low="107", close="110"),
        _candle(3, high="112", low="108", close="109"),
        _candle(4, high="113", low="109", close="112"),
        _candle(5, high="118", low="113", close="114"),
    ]


def _breakout_candles_with_distinct_early_and_recent_atr() -> list[Candle]:
    return [
        _candle(0, open_="95", high="140", low="90", close="100"),
        _candle(1, open_="100", high="150", low="95", close="105"),
        _candle(2, high="111", low="107", close="110"),
        _candle(3, high="112", low="108", close="109"),
        _candle(4, high="113", low="109", close="112"),
        _candle(5, high="118", low="113", close="114"),
    ]


def test_emits_no_signal_before_required_warmup() -> None:
    strategy = _strategy()

    signals = strategy.on_candles({}, _breakout_candles()[:-1])

    assert signals == []


def test_emits_long_open_signal_on_channel_breakout_with_atr_risk() -> None:
    strategy = _strategy()

    signals = strategy.on_candles({}, _breakout_candles())

    assert len(signals) == 1
    signal = signals[0]
    assert signal.account_id == "okx_sub_main"
    assert signal.bot_id == "okx_perp_bot_main"
    assert signal.strategy_id == "btc_channel_breakout_15m"
    assert signal.symbol == "BTC-USDT-SWAP"
    assert signal.run_id == "run-1"
    assert signal.timeframe == "15m"
    assert signal.action == "open"
    assert signal.direction == "long"
    assert signal.stop_loss_pct == pytest.approx(8 / 114)
    assert signal.take_profit_pct == pytest.approx((8 / 114) * 3)


def test_uses_recent_atr_window_immediately_before_breakout() -> None:
    strategy = _strategy(max_atr_pct=1)

    signals = strategy.on_candles({}, _breakout_candles_with_distinct_early_and_recent_atr())

    assert len(signals) == 1
    assert signals[0].stop_loss_pct == pytest.approx(8 / 114)
    assert signals[0].take_profit_pct == pytest.approx((8 / 114) * 3)


def test_sorts_candles_by_timestamp_before_channel_and_atr_windows() -> None:
    strategy = _strategy()
    candles = list(reversed(_breakout_candles()))

    signals = strategy.on_candles({}, candles)

    assert len(signals) == 1
    assert signals[0].stop_loss_pct == pytest.approx(8 / 114)


def test_atr_uses_previous_close_before_recent_atr_window_for_gap_risk() -> None:
    strategy = _strategy(max_atr_pct=1)
    candles = [
        _candle(0, high="101", low="99", close="100"),
        _candle(1, high="101", low="99", close="100"),
        _candle(2, high="101", low="99", close="100"),
        _candle(3, high="151", low="149", close="150"),
        _candle(4, high="153", low="151", close="152"),
        _candle(5, high="160", low="154", close="156"),
    ]

    signals = strategy.on_candles({}, candles)

    assert len(signals) == 1
    assert signals[0].stop_loss_pct == pytest.approx(54 / 156)


def test_donchian_channel_excludes_latest_candle_high() -> None:
    strategy = _strategy()
    candles = _breakout_candles()
    candles[-1] = _candle(5, high="125", low="113", close="114")

    signals = strategy.on_candles({}, candles)

    assert len(signals) == 1


def test_ignores_unconfirmed_and_other_symbol_candles() -> None:
    strategy = _strategy()
    candles = _breakout_candles()
    candles.insert(4, _candle(4, symbol="ETH-USDT-SWAP", high="200", low="50", close="200"))
    candles.append(_candle(6, high="130", low="129", close="130", confirmed=False))

    signals = strategy.on_candles({}, candles)

    assert len(signals) == 1
    assert signals[0].symbol == "BTC-USDT-SWAP"
    assert signals[0].stop_loss_pct == pytest.approx(8 / 114)


def test_emits_no_signal_when_latest_close_does_not_break_prior_channel_high() -> None:
    strategy = _strategy()
    candles = _breakout_candles()
    candles[-1] = _candle(5, high="114", low="110", close="113")

    signals = strategy.on_candles({}, candles)

    assert signals == []


def test_skips_signal_when_atr_percent_outside_bounds() -> None:
    low_atr_strategy = _strategy(min_atr_pct=0.2, max_atr_pct=1)
    high_atr_strategy = _strategy(max_atr_pct=0.01)
    candles = _breakout_candles()

    assert low_atr_strategy.on_candles({}, candles) == []
    assert high_atr_strategy.on_candles({}, candles) == []


@pytest.mark.parametrize(
    ("param", "value"),
    [
        ("lookback", 0),
        ("atr_period", 0),
        ("atr_multiplier", 0),
        ("reward_risk", 0),
        ("min_atr_pct", 0),
        ("max_atr_pct", 0),
    ],
)
def test_rejects_non_positive_parameters(param: str, value: object) -> None:
    with pytest.raises(ValueError, match=param):
        _strategy(**{param: value})


def test_rejects_min_atr_pct_above_max_atr_pct() -> None:
    with pytest.raises(ValueError, match="min_atr_pct"):
        _strategy(min_atr_pct=0.09, max_atr_pct=0.08)
