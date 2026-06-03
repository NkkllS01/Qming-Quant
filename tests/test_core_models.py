from datetime import datetime, timezone
from decimal import Decimal

from core.models import Candle, Signal


def test_candle_from_okx_row_normalizes_confirmed_values() -> None:
    candle = Candle.from_okx_row(
        symbol="BTC-USDT-SWAP",
        timeframe="1m",
        row=[
            "1717200000000",
            "100.1",
            "101.2",
            "99.9",
            "100.8",
            "123",
            "12.3",
            "1234.5",
            "1",
        ],
    )

    assert candle.symbol == "BTC-USDT-SWAP"
    assert candle.timeframe == "1m"
    assert candle.timestamp == datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert candle.open == Decimal("100.1")
    assert candle.high == Decimal("101.2")
    assert candle.low == Decimal("99.9")
    assert candle.close == Decimal("100.8")
    assert candle.volume == Decimal("123")
    assert candle.confirmed is True


def test_signal_carries_trade_lineage_fields() -> None:
    signal = Signal(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="run-1",
        action="open",
        direction="long",
        confidence=0.75,
        timeframe="15m",
        reason="trend breakout",
    )

    assert signal.account_id == "okx_sub_main"
    assert signal.bot_id == "okx_perp_bot_main"
    assert signal.strategy_id == "btc_trend_15m"
    assert signal.symbol == "BTC-USDT-SWAP"
    assert signal.run_id == "run-1"

