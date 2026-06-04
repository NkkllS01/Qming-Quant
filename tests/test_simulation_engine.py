from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.models import Candle
from core.models import Signal
from simulation.engine import SimulationTradingEngine
from strategies.examples.trend import MultiTimeframeTrendStrategy


def _candle(ts: datetime, close: Decimal) -> Candle:
    return Candle(
        symbol="BTC-USDT-SWAP",
        timeframe="15m",
        timestamp=ts,
        open=close - Decimal("1"),
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=Decimal("100"),
        confirmed=True,
    )


def test_simulation_trading_engine_runs_strategy_through_risk_and_broker() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [_candle(start + timedelta(minutes=15 * i), Decimal(100 + i)) for i in range(40)]
    strategy = MultiTimeframeTrendStrategy(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="sim-run-1",
    )
    engine = SimulationTradingEngine(initial_equity=Decimal("1000"))

    result = engine.run(strategy, candles)

    assert result.signals_count >= 1
    assert result.approved_count >= 1
    assert result.rejected_count == 0
    assert result.fills_count >= 1
    assert result.positions_count <= 1
    assert len(result.fills) >= 1
    assert result.final_equity >= Decimal("1000")
    assert result.journal[-1].event_type in {"fill", "exit_take_profit"}


def test_simulation_trading_engine_records_risk_rejection() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [_candle(start + timedelta(minutes=15 * i), Decimal(100 + i)) for i in range(40)]
    strategy = MultiTimeframeTrendStrategy(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="sim-run-1",
    )
    engine = SimulationTradingEngine(initial_equity=Decimal("1000"), max_open_positions=0)

    result = engine.run(strategy, candles)

    assert result.signals_count >= 1
    assert result.approved_count == 0
    assert result.rejected_count >= 1
    assert result.fills_count == 0
    assert result.positions_count == 0
    assert result.journal[-1].event_type == "risk_rejected"


def test_simulation_trading_engine_rejects_when_daily_loss_limit_is_reached() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [_candle(start + timedelta(minutes=15 * i), Decimal(100 + i)) for i in range(2)]
    engine = SimulationTradingEngine(
        initial_equity=Decimal("1000"),
        current_daily_loss=Decimal("30"),
    )

    result = engine.run(OneShotLongStrategy(), candles)

    assert result.approved_count == 0
    assert result.fills_count == 0
    assert result.journal[-1].event_type == "risk_rejected"
    assert result.journal[-1].message == "daily loss limit reached"


def test_simulation_trading_engine_rejects_when_drawdown_pause_is_reached() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [_candle(start + timedelta(minutes=15 * i), Decimal(100 + i)) for i in range(2)]
    engine = SimulationTradingEngine(
        initial_equity=Decimal("1000"),
        current_drawdown=Decimal("0.08"),
    )

    result = engine.run(OneShotLongStrategy(), candles)

    assert result.approved_count == 0
    assert result.fills_count == 0
    assert result.journal[-1].event_type == "risk_rejected"
    assert result.journal[-1].message == "drawdown pause reached"


class OneShotLongStrategy:
    account_id = "okx_sub_main"
    bot_id = "okx_perp_bot_main"
    strategy_id = "one_shot_long"
    symbol = "BTC-USDT-SWAP"
    run_id = "sim-run-1"
    timeframe = "15m"

    def __init__(self) -> None:
        self.emitted = False

    def on_candles(self, context: dict, candles: list[Candle]) -> list[Signal]:
        if self.emitted:
            return []
        self.emitted = True
        return [
            Signal(
                account_id=self.account_id,
                bot_id=self.bot_id,
                strategy_id=self.strategy_id,
                symbol=self.symbol,
                run_id=self.run_id,
                action="open",
                direction="long",
                confidence=1.0,
                timeframe=self.timeframe,
                reason="test entry",
                stop_loss_pct=0.01,
                take_profit_pct=0.02,
            )
        ]


def test_simulation_trading_engine_fills_signal_on_next_candle_open() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        _candle(start, Decimal("100")),
        Candle(
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            timestamp=start + timedelta(minutes=15),
            open=Decimal("120"),
            high=Decimal("121"),
            low=Decimal("119"),
            close=Decimal("120"),
            volume=Decimal("100"),
            confirmed=True,
        ),
    ]
    engine = SimulationTradingEngine(initial_equity=Decimal("1000"))

    result = engine.run(OneShotLongStrategy(), candles)

    assert result.fills_count == 1
    assert result.fills[0].price == Decimal("120")
    assert result.positions[0].entry_price == Decimal("120")
    assert result.fills[0].fill_id == "sim-1"


def test_simulation_trading_engine_closes_position_when_take_profit_is_hit() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        _candle(start, Decimal("100")),
        Candle(
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            timestamp=start + timedelta(minutes=15),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("100"),
            confirmed=True,
        ),
        Candle(
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            timestamp=start + timedelta(minutes=30),
            open=Decimal("101"),
            high=Decimal("103"),
            low=Decimal("100"),
            close=Decimal("102"),
            volume=Decimal("100"),
            confirmed=True,
        ),
    ]
    engine = SimulationTradingEngine(initial_equity=Decimal("1000"), default_size=Decimal("1"))

    result = engine.run(OneShotLongStrategy(), candles)

    assert result.fills_count == 2
    assert result.fills[-1].side == "sell"
    assert result.fills[-1].price == Decimal("102.00")
    assert result.positions_count == 0
    assert result.final_equity == Decimal("1002.00")
    assert result.journal[-1].event_type == "exit_take_profit"


def test_simulation_trading_engine_closes_position_at_stop_loss_before_take_profit() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        _candle(start, Decimal("100")),
        Candle(
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            timestamp=start + timedelta(minutes=15),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("100"),
            confirmed=True,
        ),
        Candle(
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            timestamp=start + timedelta(minutes=30),
            open=Decimal("100"),
            high=Decimal("103"),
            low=Decimal("98"),
            close=Decimal("101"),
            volume=Decimal("100"),
            confirmed=True,
        ),
    ]
    engine = SimulationTradingEngine(initial_equity=Decimal("1000"), default_size=Decimal("1"))

    result = engine.run(OneShotLongStrategy(), candles)

    assert result.fills_count == 2
    assert result.fills[-1].price == Decimal("99.00")
    assert result.positions_count == 0
    assert result.final_equity == Decimal("999.00")
    assert result.journal[-1].event_type == "exit_stop_loss"
