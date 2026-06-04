from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backtest.engine import BacktestEngine
from core.models import Candle, OrderIntent, Signal
from execution.order_factory import OrderFactory
from risk.manager import PortfolioRiskManager
from risk.symbol_lease import SymbolLeaseManager
from simulation.broker import SimulationBroker
from paper.broker import PaperBroker
from strategies.examples.trend import MultiTimeframeTrendStrategy
from strategies.runner import StrategyRunner


def _candle(ts: datetime, close: Decimal, timeframe: str = "15m") -> Candle:
    return Candle(
        symbol="BTC-USDT-SWAP",
        timeframe=timeframe,
        timestamp=ts,
        open=close - Decimal("1"),
        high=close + Decimal("2"),
        low=close - Decimal("2"),
        close=close,
        volume=Decimal("100"),
        confirmed=True,
    )


def test_strategy_runner_returns_signals_from_strategy() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [_candle(start + timedelta(minutes=15 * i), Decimal(100 + i)) for i in range(40)]
    strategy = MultiTimeframeTrendStrategy(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="run-1",
    )

    signals = StrategyRunner(strategy).run_on_candles(candles)

    assert signals
    assert signals[-1].action == "open"
    assert signals[-1].direction == "long"


def test_multi_timeframe_trend_strategy_filters_against_higher_timeframe_downtrend() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    entry_candles = [_candle(start + timedelta(minutes=15 * i), Decimal(100 + i)) for i in range(80)]
    higher_candles = [
        _candle(start + timedelta(hours=i), Decimal(200 - i), timeframe="1h") for i in range(80)
    ]
    strategy = MultiTimeframeTrendStrategy(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="run-1",
        higher_timeframe="1h",
        fast_ema_period=5,
        slow_ema_period=20,
        atr_period=14,
    )

    signals = StrategyRunner(strategy).run_on_candles(
        entry_candles,
        context={"higher_timeframe_candles": higher_candles},
    )

    assert signals == []


def test_multi_timeframe_trend_strategy_uses_atr_for_risk_percentages() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [_candle(start + timedelta(minutes=15 * i), Decimal(100 + i)) for i in range(80)]
    strategy = MultiTimeframeTrendStrategy(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="run-1",
        fast_ema_period=5,
        slow_ema_period=20,
        atr_period=14,
        atr_stop_multiplier=2,
        reward_risk=3,
    )

    signals = StrategyRunner(strategy).run_on_candles(candles)

    assert signals
    assert signals[-1].reason == "multi-timeframe EMA trend breakout"
    assert signals[-1].stop_loss_pct is not None
    assert round(signals[-1].stop_loss_pct, 6) == round(float(Decimal("8") / Decimal("179")), 6)
    assert signals[-1].take_profit_pct is not None
    assert round(signals[-1].take_profit_pct, 6) == round(signals[-1].stop_loss_pct * 3, 6)


def test_portfolio_risk_rejects_order_when_open_position_limit_reached() -> None:
    signal = Signal(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="run-1",
        action="open",
        direction="long",
        confidence=0.8,
        timeframe="15m",
        reason="test",
    )
    manager = PortfolioRiskManager(max_open_positions=0)

    decision = manager.evaluate(signal, equity=Decimal("1000"), open_positions=0)

    assert decision.approved is False
    assert "open position" in decision.reason


def test_symbol_lease_allows_only_owner_to_open_symbol() -> None:
    leases = SymbolLeaseManager()
    leases.acquire("BTC-USDT-SWAP", "btc_trend_15m")

    assert leases.can_open("BTC-USDT-SWAP", "btc_trend_15m") is True
    assert leases.can_open("BTC-USDT-SWAP", "btc_breakout_15m") is False


def test_order_factory_quantizes_size_and_price() -> None:
    signal = Signal(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="run-1",
        action="open",
        direction="long",
        confidence=0.8,
        timeframe="15m",
        reason="test",
    )

    order = OrderFactory().from_signal(
        signal,
        size=Decimal("0.123"),
        price=Decimal("100.18"),
        tick_size=Decimal("0.1"),
        lot_size=Decimal("0.01"),
        min_size=Decimal("0.01"),
    )

    assert order.size == Decimal("0.12")
    assert order.price == Decimal("100.1")
    assert order.client_order_id.startswith("okx_perp_bot_main-btc_trend_15m-BTC")


def test_order_factory_adds_sequence_to_keep_client_order_ids_unique(monkeypatch) -> None:
    class FixedDateTime:
        @classmethod
        def now(cls, tz: timezone) -> datetime:
            return datetime(2024, 1, 1, 0, 0, 0, tzinfo=tz)

    monkeypatch.setattr("execution.order_factory.datetime", FixedDateTime)
    signal = Signal(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="run-1",
        action="open",
        direction="long",
        confidence=0.8,
        timeframe="15m",
        reason="test",
    )
    factory = OrderFactory()

    first = factory.from_signal(
        signal,
        size=Decimal("0.1"),
        price=None,
        tick_size=Decimal("0.1"),
        lot_size=Decimal("0.01"),
        min_size=Decimal("0.01"),
    )
    second = factory.from_signal(
        signal,
        size=Decimal("0.1"),
        price=None,
        tick_size=Decimal("0.1"),
        lot_size=Decimal("0.01"),
        min_size=Decimal("0.01"),
    )

    assert first.client_order_id != second.client_order_id
    assert first.client_order_id.endswith("-000001")
    assert second.client_order_id.endswith("-000002")


def test_order_factory_rejects_size_below_min_size_after_quantization() -> None:
    signal = Signal(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="run-1",
        action="open",
        direction="long",
        confidence=0.8,
        timeframe="15m",
        reason="test",
    )

    try:
        OrderFactory().from_signal(
            signal,
            size=Decimal("0.009"),
            price=None,
            tick_size=Decimal("0.1"),
            lot_size=Decimal("0.01"),
            min_size=Decimal("0.01"),
        )
    except ValueError as exc:
        assert "minimum order size" in str(exc)
    else:
        raise AssertionError("expected minimum order size rejection")


def test_simulation_broker_fills_market_order_and_updates_position() -> None:
    broker = SimulationBroker(initial_equity=Decimal("1000"))
    intent = OrderIntent(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="run-1",
        side="buy",
        position_action="open",
        order_type="market",
        size=Decimal("0.1"),
        price=None,
        reduce_only=False,
        client_order_id="test-1",
    )

    fill = broker.execute(intent, market_price=Decimal("100"))

    assert fill.price == Decimal("100")
    assert broker.positions["BTC-USDT-SWAP"].size == Decimal("0.1")


def test_paper_broker_keeps_legacy_fill_id_prefix() -> None:
    broker = PaperBroker(initial_equity=Decimal("1000"))
    intent = OrderIntent(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="run-1",
        side="buy",
        position_action="open",
        order_type="market",
        size=Decimal("0.1"),
        price=None,
        reduce_only=False,
        client_order_id="test-1",
    )

    fill = broker.execute(intent, market_price=Decimal("100"))

    assert fill.fill_id == "paper-1"


def test_backtest_engine_generates_metrics_from_strategy() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [_candle(start + timedelta(minutes=15 * i), Decimal(100 + i)) for i in range(60)]
    strategy = MultiTimeframeTrendStrategy(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="run-1",
    )

    result = BacktestEngine(initial_equity=Decimal("1000")).run(strategy, candles)

    assert result.metrics.total_trades >= 1
    assert result.final_equity > Decimal("0")


class OneShotLongStrategy:
    account_id = "okx_sub_main"
    bot_id = "okx_perp_bot_main"
    strategy_id = "one_shot_long"
    symbol = "BTC-USDT-SWAP"
    run_id = "run-1"
    timeframe = "15m"

    def __init__(self, *, stop_loss_pct: float = 0.01, take_profit_pct: float = 0.02) -> None:
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
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
                stop_loss_pct=self.stop_loss_pct,
                take_profit_pct=self.take_profit_pct,
            )
        ]


class ScriptedLongStrategy:
    account_id = "okx_sub_main"
    bot_id = "okx_perp_bot_main"
    strategy_id = "scripted_long"
    symbol = "BTC-USDT-SWAP"
    run_id = "run-1"
    timeframe = "15m"

    def __init__(self, emit_on_lengths: set[int]) -> None:
        self.emit_on_lengths = emit_on_lengths
        self.emitted_lengths: set[int] = set()

    def on_candles(self, context: dict, candles: list[Candle]) -> list[Signal]:
        length = len(candles)
        if length not in self.emit_on_lengths or length in self.emitted_lengths:
            return []
        self.emitted_lengths.add(length)
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
                reason=f"scripted entry at {length}",
                stop_loss_pct=0.01,
                take_profit_pct=0.02,
            )
        ]


def test_backtest_closes_long_trade_at_take_profit_and_updates_equity() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        _candle(start, Decimal("100")),
        Candle(
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            timestamp=start + timedelta(minutes=15),
            open=Decimal("100"),
            high=Decimal("103"),
            low=Decimal("100"),
            close=Decimal("102"),
            volume=Decimal("100"),
            confirmed=True,
        ),
    ]

    result = BacktestEngine(
        initial_equity=Decimal("1000"),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
        default_size=Decimal("1"),
    ).run(OneShotLongStrategy(), candles)

    assert result.metrics.total_trades == 1
    assert result.metrics.win_rate == 1.0
    assert result.trades[0].exit_reason == "take_profit"
    assert result.trades[0].exit_price == Decimal("102.00")
    assert result.trades[0].pnl == Decimal("2.00")
    assert result.final_equity == Decimal("1002.00")
    assert result.equity_curve[-1].equity == Decimal("1002.00")


def test_backtest_fills_signal_on_next_candle_open_not_signal_close() -> None:
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

    result = BacktestEngine(
        initial_equity=Decimal("1000"),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
        default_size=Decimal("1"),
    ).run(OneShotLongStrategy(), candles)

    assert result.trades[0].entry_price == Decimal("120.00")
    assert result.trades[0].opened_at == start + timedelta(minutes=15)
    assert result.trades[0].exit_reason == "end_of_data"
    assert result.final_equity == Decimal("1000.00")


def test_backtest_closes_long_trade_at_stop_loss_and_tracks_drawdown() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        _candle(start, Decimal("100")),
        Candle(
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            timestamp=start + timedelta(minutes=15),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("99"),
            volume=Decimal("100"),
            confirmed=True,
        ),
    ]

    result = BacktestEngine(
        initial_equity=Decimal("1000"),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
        default_size=Decimal("1"),
    ).run(OneShotLongStrategy(), candles)

    assert result.metrics.total_trades == 1
    assert result.metrics.win_rate == 0.0
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.trades[0].exit_price == Decimal("99.00")
    assert result.trades[0].pnl == Decimal("-1.00")
    assert result.final_equity == Decimal("999.00")
    assert result.metrics.max_drawdown == Decimal("0.001")


def test_backtest_metrics_include_profit_factor_loss_streak_and_hold_time() -> None:
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
            high=Decimal("102"),
            low=Decimal("100"),
            close=Decimal("102"),
            volume=Decimal("100"),
            confirmed=True,
        ),
        Candle(
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            timestamp=start + timedelta(minutes=45),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("99"),
            close=Decimal("99"),
            volume=Decimal("100"),
            confirmed=True,
        ),
    ]

    result = BacktestEngine(
        initial_equity=Decimal("1000"),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
        default_size=Decimal("1"),
    ).run(ScriptedLongStrategy(emit_on_lengths={1, 3}), candles)

    assert result.metrics.total_trades == 2
    assert result.metrics.gross_profit == Decimal("2.00")
    assert result.metrics.gross_loss == Decimal("1.00")
    assert result.metrics.profit_factor == Decimal("2")
    assert result.metrics.average_win == Decimal("2.00")
    assert result.metrics.average_loss == Decimal("1.00")
    assert result.metrics.payoff_ratio == Decimal("2")
    assert result.metrics.max_consecutive_losses == 1
    assert result.metrics.average_holding_seconds == Decimal("450")
