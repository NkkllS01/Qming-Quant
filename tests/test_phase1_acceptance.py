from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.main import AppServices, build_parser, run_command
from core.models import Candle, Instrument
from storage.repositories import CandleRepository, InstrumentRepository
from storage.trade_repository import TradeRepository


def test_phase1_local_data_to_backtest_and_sim_persistence_acceptance() -> None:
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
