import json
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.cli_fakes import FakeGateway, ma_crossover_candles
from app.main import AppServices, build_parser, run_command
from core.models import Candle, FundingRate, Instrument
from storage.repositories import (
    CandleRepository,
    FundingRateRepository,
    InstrumentRepository,
)
from storage.trade_repository import TradeRepository






def test_run_backtest_command_reads_repository_and_returns_metrics() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
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
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    instrument_repo.upsert_many(
        [
            Instrument(
                symbol="BTC-USDT-SWAP",
                inst_type="SWAP",
                tick_size=Decimal("0.5"),
                lot_size=Decimal("0.03"),
                min_size=Decimal("0.03"),
                state="live",
            )
        ]
    )
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=repo,
        instrument_repository=instrument_repo,
    )
    args = build_parser().parse_args(["backtest", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m"])

    output = run_command(args, services)

    assert "total_trades=" in output
    assert "final_equity=" in output
    assert "win_rate=" in output
    assert "max_drawdown=" in output
    assert "profit_factor=" in output
    assert "payoff_ratio=" in output
    assert "max_consecutive_losses=" in output
    assert "average_holding_seconds=" in output
    assert "total_fees=" in output
    assert "start=all" in output
    assert "end=all" in output
    assert "tick_size=0.5" in output
    assert "lot_size=0.03" in output
    assert "min_size=0.03" in output


def test_run_backtest_command_can_use_ma_crossover_strategy() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(ma_crossover_candles(start))
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(
        [
            "backtest",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "15m",
            "--strategy",
            "ma-crossover",
        ]
    )

    output = run_command(args, services)

    assert "strategy=ma-crossover" in output
    assert "total_trades=" in output


def test_run_backtest_command_blocks_missing_candles_by_default() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
                timestamp=start,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=Decimal("100"),
                confirmed=True,
            ),
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
                timestamp=start + timedelta(minutes=30),
                open=Decimal("102"),
                high=Decimal("103"),
                low=Decimal("101"),
                close=Decimal("102"),
                volume=Decimal("100"),
                confirmed=True,
            ),
        ]
    )
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(["backtest", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m"])

    output = run_command(args, services)

    assert "data_gate status=blocked" in output
    assert "reason=missing_candles" in output
    assert "missing_ranges=1" in output


def test_run_backtest_command_blocks_insufficient_candles_by_default() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
                timestamp=start + timedelta(minutes=15 * i),
                open=Decimal(99 + i),
                high=Decimal(102 + i),
                low=Decimal(98 + i),
                close=Decimal(100 + i),
                volume=Decimal("100"),
                confirmed=True,
            )
            for i in range(2)
        ]
    )
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(["backtest", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m"])

    output = run_command(args, services)

    assert "data_gate status=blocked" in output
    assert "reason=insufficient_candles" in output
    assert "actual_count=2" in output
    assert "min_candles=30" in output


def test_run_backtest_command_allows_lower_min_candles_when_explicit() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
                timestamp=start + timedelta(minutes=15 * i),
                open=Decimal(99 + i),
                high=Decimal(102 + i),
                low=Decimal(98 + i),
                close=Decimal(100 + i),
                volume=Decimal("100"),
                confirmed=True,
            )
            for i in range(2)
        ]
    )
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(
        ["backtest", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m", "--min-candles", "2"]
    )

    output = run_command(args, services)

    assert "total_trades=" in output
    assert "reason=insufficient_candles" not in output


def test_run_backtest_command_filters_candles_by_time_range() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
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
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(
        [
            "backtest",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "15m",
            "--start",
            "2024-01-01T02:30:00Z",
            "--end",
            "2024-01-01T03:15:00Z",
            "--min-candles",
            "4",
        ]
    )

    output = run_command(args, services)

    assert "total_trades=" in output
    assert "start=2024-01-01T02:30:00Z" in output
    assert "end=2024-01-01T03:15:00Z" in output
    assert "reason=insufficient_candles" not in output


def test_run_backtest_command_writes_json_report() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    funding_repo = FundingRateRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
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
    instrument_repo.upsert_many(
        [
            Instrument(
                symbol="BTC-USDT-SWAP",
                inst_type="SWAP",
                tick_size=Decimal("0.5"),
                lot_size=Decimal("0.03"),
                min_size=Decimal("0.03"),
                state="live",
            )
        ]
    )
    funding_repo.upsert_many(
        [
            FundingRate(
                symbol="BTC-USDT-SWAP",
                funding_time=start,
                funding_rate=Decimal("0.0001"),
                realized_rate=Decimal("0.00009"),
            ),
            FundingRate(
                symbol="BTC-USDT-SWAP",
                funding_time=start + timedelta(hours=8),
                funding_rate=Decimal("-0.0002"),
                realized_rate=Decimal("-0.00018"),
            ),
            FundingRate(
                symbol="BTC-USDT-SWAP",
                funding_time=start + timedelta(hours=16),
                funding_rate=Decimal("0.0003"),
                realized_rate=Decimal("0.00029"),
            ),
        ]
    )
    report_path = Path(".pytest_cache") / "reports" / "bt.json"
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=repo,
        instrument_repository=instrument_repo,
        funding_rate_repository=funding_repo,
    )
    args = build_parser().parse_args(
        [
            "backtest",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "15m",
            "--start",
            "2024-01-01T00:00:00Z",
            "--end",
            "2024-01-01T14:45:00Z",
            "--report-json",
            str(report_path),
        ]
    )

    output = run_command(args, services)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert f"report_json={report_path}" in output
    assert report["system"] == "Qiming Quant"
    assert report["command"] == "backtest"
    assert report["symbol"] == "BTC-USDT-SWAP"
    assert report["timeframe"] == "15m"
    assert report["data_window"]["start"] == "2024-01-01T00:00:00Z"
    assert report["data_window"]["end"] == "2024-01-01T14:45:00Z"
    assert report["data_window"]["candle_count"] == 60
    assert report["data_gate"]["status"] == "passed"
    assert report["data_gate"]["reason"] == "ok"
    assert report["data_gate"]["candle_count"] == 60
    assert report["instrument"]["lot_size"] == "0.03"
    assert report["funding_rates"]["status"] == "available"
    assert report["funding_rates"]["count"] == 2
    assert report["funding_rates"]["average_rate"] == "-0.00005"
    assert report["funding_rates"]["min_rate"] == "-0.0002"
    assert report["funding_rates"]["max_rate"] == "0.0001"
    assert report["funding_rates"]["first_funding_time"] == "2024-01-01T00:00:00+00:00"
    assert report["funding_rates"]["last_funding_time"] == "2024-01-01T08:00:00+00:00"
    assert "total_trades" in report["metrics"]
    assert "final_equity" in report
    assert isinstance(report["trades"], list)
    assert isinstance(report["equity_curve"], list)


def test_run_backtest_command_writes_blocked_json_report() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
                timestamp=start + timedelta(minutes=15 * i),
                open=Decimal(99 + i),
                high=Decimal(102 + i),
                low=Decimal(98 + i),
                close=Decimal(100 + i),
                volume=Decimal("100"),
                confirmed=True,
            )
            for i in range(2)
        ]
    )
    report_path = Path(".pytest_cache") / "reports" / "blocked_bt.json"
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(
        [
            "backtest",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "15m",
            "--report-json",
            str(report_path),
        ]
    )

    output = run_command(args, services)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "data_gate status=blocked" in output
    assert f"report_json={report_path}" in output
    assert report["status"] == "blocked"
    assert report["symbol"] == "BTC-USDT-SWAP"
    assert report["data_window"]["candle_count"] == 2
    assert report["data_gate"]["status"] == "blocked"
    assert report["data_gate"]["reason"] == "insufficient_candles"
    assert report["funding_rates"]["status"] == "unavailable"
    assert report["funding_rates"]["count"] == 0
    assert report["metrics"] is None
    assert report["trades"] == []
    assert report["equity_curve"] == []


def test_run_backtest_command_checks_gaps_inside_filtered_range() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
                timestamp=start + timedelta(minutes=15 * i),
                open=Decimal(99 + i),
                high=Decimal(102 + i),
                low=Decimal(98 + i),
                close=Decimal(100 + i),
                volume=Decimal("100"),
                confirmed=True,
            )
            for i in [0, 1, 4, 5, 6, 7]
        ]
    )
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(
        [
            "backtest",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "15m",
            "--start",
            "2024-01-01T00:00:00Z",
            "--end",
            "2024-01-01T01:45:00Z",
            "--min-candles",
            "4",
        ]
    )

    output = run_command(args, services)

    assert "data_gate status=blocked" in output
    assert "reason=missing_candles" in output
    assert "first_missing=2024-01-01T00:30:00+00:00->2024-01-01T00:45:00+00:00" in output


def test_run_backtest_command_allows_missing_candles_when_explicit() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
                timestamp=start + timedelta(minutes=30 * i),
                open=Decimal(99 + i),
                high=Decimal(102 + i),
                low=Decimal(98 + i),
                close=Decimal(100 + i),
                volume=Decimal("100"),
                confirmed=True,
            )
            for i in range(40)
        ]
    )
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(
        ["backtest", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m", "--allow-gaps"]
    )

    output = run_command(args, services)

    assert "total_trades=" in output
    assert "data_gate status=blocked" not in output


def test_run_sim_run_command_reads_repository_and_returns_summary() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    trade_repo = TradeRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
                timestamp=start + timedelta(minutes=15 * i),
                open=Decimal(99 + i),
                high=Decimal(102 + i),
                low=Decimal(98 + i),
                close=Decimal(100 + i),
                volume=Decimal("100"),
                confirmed=True,
            )
            for i in range(40)
        ]
    )
    instrument_repo.upsert_many(
        [
            Instrument(
                symbol="BTC-USDT-SWAP",
                inst_type="SWAP",
                tick_size=Decimal("0.5"),
                lot_size=Decimal("0.03"),
                min_size=Decimal("0.03"),
                state="live",
            )
        ]
    )
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=repo,
        instrument_repository=instrument_repo,
        trade_repository=trade_repo,
    )
    args = build_parser().parse_args(["sim-run", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m"])

    output = run_command(args, services)

    assert "sim_run" in output
    assert "fills=" in output
    assert "start=all" in output
    assert "end=all" in output
    assert "positions=" in output
    assert "persisted=true" in output
    assert len(trade_repo.list_fills("cli-sim")) >= 1
    assert trade_repo.list_fills("cli-sim")[0].size == Decimal("0.09")
    assert len(trade_repo.list_positions("cli-sim")) <= 1
    assert len(trade_repo.list_journal("cli-sim")) >= 1
    assert "lot_size=0.03" in output


def test_run_sim_run_command_can_use_ma_crossover_strategy() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    trade_repo = TradeRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(ma_crossover_candles(start))
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=repo,
        trade_repository=trade_repo,
    )
    args = build_parser().parse_args(
        [
            "sim-run",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "15m",
            "--strategy",
            "ma-crossover",
        ]
    )

    output = run_command(args, services)

    assert "strategy=ma-crossover" in output
    assert "signals=" in output
    assert "persisted=true" in output
    assert len(trade_repo.list_journal("cli-sim")) >= 1


def test_run_sim_run_command_persists_daily_loss_risk_rejection() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    trade_repo = TradeRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(ma_crossover_candles(start))
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=repo,
        trade_repository=trade_repo,
    )
    args = build_parser().parse_args(
        [
            "sim-run",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "15m",
            "--strategy",
            "ma-crossover",
            "--current-daily-loss",
            "30",
        ]
    )

    output = run_command(args, services)

    assert "approved=0" in output
    assert "fills=0" in output
    assert "persisted=true" in output
    journal = trade_repo.list_journal("cli-sim")
    assert journal[-1].event_type == "risk_rejected"
    assert journal[-1].message == "daily loss limit reached"


def test_run_sim_run_command_blocks_missing_candles_by_default() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
                timestamp=start,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=Decimal("100"),
                confirmed=True,
            ),
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
                timestamp=start + timedelta(minutes=30),
                open=Decimal("102"),
                high=Decimal("103"),
                low=Decimal("101"),
                close=Decimal("102"),
                volume=Decimal("100"),
                confirmed=True,
            ),
        ]
    )
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(["sim-run", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m"])

    output = run_command(args, services)

    assert "sim_run data_gate status=blocked" in output
    assert "reason=missing_candles" in output


def test_run_sim_run_command_blocks_insufficient_candles_by_default() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
                timestamp=start + timedelta(minutes=15 * i),
                open=Decimal(99 + i),
                high=Decimal(102 + i),
                low=Decimal(98 + i),
                close=Decimal(100 + i),
                volume=Decimal("100"),
                confirmed=True,
            )
            for i in range(2)
        ]
    )
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(["sim-run", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m"])

    output = run_command(args, services)

    assert "sim_run data_gate status=blocked" in output
    assert "reason=insufficient_candles" in output


def test_run_sim_run_command_filters_candles_by_time_range() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    trade_repo = TradeRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="15m",
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
        gateway=FakeGateway(),
        candle_repository=repo,
        trade_repository=trade_repo,
    )
    args = build_parser().parse_args(
        [
            "sim-run",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "15m",
            "--start",
            "2024-01-01T02:30:00Z",
            "--end",
            "2024-01-01T03:15:00Z",
            "--min-candles",
            "4",
        ]
    )

    output = run_command(args, services)

    assert "sim_run" in output
    assert "start=2024-01-01T02:30:00Z" in output
    assert "end=2024-01-01T03:15:00Z" in output
    assert "persisted=true" in output
