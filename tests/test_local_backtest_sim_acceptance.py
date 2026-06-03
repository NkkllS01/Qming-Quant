from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.main import AppServices, build_parser, run_command
from core.models import Candle, Instrument
from storage.repositories import CandleRepository, InstrumentRepository
from storage.trade_repository import TradeRepository


def test_local_data_to_backtest_and_sim_persistence_acceptance() -> None:
    candle_repo = CandleRepository("sqlite:///:memory:")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    trade_repo = TradeRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    symbol = "BTC-USDT-SWAP"
    timeframe = "15m"

    instrument_repo.upsert_many(
        [
            Instrument(
                symbol=symbol,
                inst_type="SWAP",
                tick_size=Decimal("0.5"),
                lot_size=Decimal("0.03"),
                min_size=Decimal("0.03"),
                state="live",
            )
        ]
    )
    candle_repo.upsert_many(
        [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=start + timedelta(minutes=15 * i),
                open=Decimal(99 + i),
                high=Decimal(102 + i),
                low=Decimal(98 + i),
                close=Decimal(100 + i),
                volume=Decimal("100"),
                confirmed=True,
            )
            for i in range(60)
        ]
    )

    services = AppServices(
        gateway=object(),
        candle_repository=candle_repo,
        instrument_repository=instrument_repo,
        trade_repository=trade_repo,
    )
    parser = build_parser()

    backtest_output = run_command(
        parser.parse_args(["backtest", "--symbol", symbol, "--timeframe", timeframe]),
        services,
    )
    sim_output = run_command(
        parser.parse_args(["sim-run", "--symbol", symbol, "--timeframe", timeframe]),
        services,
    )

    assert "total_trades=" in backtest_output
    assert "profit_factor=" in backtest_output
    assert "tick_size=0.5" in backtest_output
    assert "sim_run" in sim_output
    assert "persisted=true" in sim_output
    assert "lot_size=0.03" in sim_output
    assert candle_repo.get_sync_state(symbol, timeframe) is not None
    assert instrument_repo.get(symbol) is not None
    assert len(trade_repo.list_fills("cli-sim")) >= 1
    assert trade_repo.list_fills("cli-sim")[0].size == Decimal("0.09")
    assert len(trade_repo.list_journal("cli-sim")) >= 1


def test_ma_crossover_sim_loop_persists_fill_position_and_journal_acceptance() -> None:
    candle_repo = CandleRepository("sqlite:///:memory:")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    trade_repo = TradeRepository("sqlite:///:memory:")
    symbol = "BTC-USDT-SWAP"
    timeframe = "15m"
    _seed_instrument(instrument_repo, symbol)
    candle_repo.upsert_many(_ma_crossover_candles(symbol, timeframe))
    services = AppServices(
        gateway=object(),
        candle_repository=candle_repo,
        instrument_repository=instrument_repo,
        trade_repository=trade_repo,
    )

    output = run_command(
        build_parser().parse_args(
            ["sim-run", "--symbol", symbol, "--timeframe", timeframe, "--strategy", "ma-crossover"]
        ),
        services,
    )

    assert "sim_run" in output
    assert "strategy=ma-crossover" in output
    assert "approved=" in output
    assert "fills=" in output
    assert "positions=" in output
    assert "persisted=true" in output
    assert len(trade_repo.list_fills("cli-sim")) >= 1
    assert len(trade_repo.list_positions("cli-sim")) == 1
    assert len(trade_repo.list_journal("cli-sim")) >= 1


def _seed_instrument(repo: InstrumentRepository, symbol: str) -> None:
    repo.upsert_many(
        [
            Instrument(
                symbol=symbol,
                inst_type="SWAP",
                tick_size=Decimal("0.5"),
                lot_size=Decimal("0.03"),
                min_size=Decimal("0.03"),
                state="live",
            )
        ]
    )


def _ma_crossover_candles(symbol: str, timeframe: str) -> list[Candle]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    closes = [Decimal("100") for _ in range(28)] + [Decimal("101"), Decimal("102")]
    return [
        Candle(
            symbol=symbol,
            timeframe=timeframe,
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
