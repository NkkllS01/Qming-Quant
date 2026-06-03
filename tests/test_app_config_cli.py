import json
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings
from app.main import AppServices, build_parser, run_command
from core.models import Candle, FundingRate, Instrument
from exchanges.okx.websocket import OKXWebSocketClient, OKXWebSocketConfig
from live.state import AccountBalance
from storage.live_repository import LiveStateRepository
from storage.repositories import CandleRepository, FundingRateRepository, InstrumentRepository
from storage.safety_repository import SafetyRepository
from storage.trade_repository import TradeRepository
from tests.fakes import (
    FakeWebSocketConnector,
    FakeWebSocketSession,
    live_store_with_position_and_order,
)


def test_settings_reads_okx_credentials_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("OKX_API_KEY", "key")
    monkeypatch.setenv("OKX_SECRET_KEY", "secret")
    monkeypatch.setenv("OKX_PASSPHRASE", "passphrase")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///trade.db")

    settings = Settings.from_env()

    assert settings.okx_api_key == "key"
    assert settings.okx_secret_key == "secret"
    assert settings.okx_passphrase == "passphrase"
    assert settings.database_url == "sqlite:///trade.db"
    assert settings.default_symbols == ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    assert settings.max_risk_per_trade == Decimal("0.005")


def test_cli_parser_supports_data_sync_and_backtest_commands() -> None:
    parser = build_parser()

    sync_args = parser.parse_args(
        ["sync-candles", "--symbol", "BTC-USDT-SWAP", "--timeframe", "1m", "--pages", "2"]
    )
    sync_range_args = parser.parse_args(
        [
            "sync-candles-range",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "1m",
            "--start",
            "2024-01-01T00:00:00Z",
            "--end",
            "2024-01-01T00:02:00Z",
        ]
    )
    candle_state_args = parser.parse_args(["candle-state", "--symbol", "BTC-USDT-SWAP", "--timeframe", "1m"])
    backtest_args = parser.parse_args(
        [
            "backtest",
            "--symbol",
            "ETH-USDT-SWAP",
            "--start",
            "2024-01-01T00:00:00Z",
            "--end",
            "2024-01-01T01:00:00Z",
            "--report-json",
            "reports/backtest.json",
        ]
    )
    aggregate_args = parser.parse_args(
        [
            "aggregate-candles",
            "--symbol",
            "BTC-USDT-SWAP",
            "--source-timeframe",
            "1m",
            "--target-timeframe",
            "15m",
        ]
    )
    sim_args = parser.parse_args(["sim-run", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m"])
    paper_args = parser.parse_args(["paper-run", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m"])
    sync_instruments_args = parser.parse_args(["sync-instruments", "--inst-type", "SWAP"])
    sync_funding_args = parser.parse_args(
        ["sync-funding-rates", "--symbol", "BTC-USDT-SWAP", "--limit", "2"]
    )
    live_sync_args = parser.parse_args(
        ["live-sync", "--symbol", "BTC-USDT-SWAP", "--max-messages", "1", "--public-only"]
    )

    assert sync_args.command == "sync-candles"
    assert sync_args.symbol == "BTC-USDT-SWAP"
    assert sync_args.timeframe == "1m"
    assert sync_args.pages == 2
    assert sync_range_args.command == "sync-candles-range"
    assert sync_range_args.start == "2024-01-01T00:00:00Z"
    assert sync_range_args.end == "2024-01-01T00:02:00Z"
    assert candle_state_args.command == "candle-state"
    assert candle_state_args.symbol == "BTC-USDT-SWAP"
    assert backtest_args.command == "backtest"
    assert backtest_args.symbol == "ETH-USDT-SWAP"
    assert backtest_args.allow_gaps is False
    assert backtest_args.min_candles == 30
    assert backtest_args.start == "2024-01-01T00:00:00Z"
    assert backtest_args.end == "2024-01-01T01:00:00Z"
    assert backtest_args.report_json == "reports/backtest.json"
    assert aggregate_args.command == "aggregate-candles"
    assert aggregate_args.source_timeframe == "1m"
    assert aggregate_args.target_timeframe == "15m"
    assert sim_args.command == "sim-run"
    assert sim_args.symbol == "BTC-USDT-SWAP"
    assert paper_args.command == "paper-run"
    assert paper_args.symbol == "BTC-USDT-SWAP"
    assert sync_instruments_args.command == "sync-instruments"
    assert sync_instruments_args.inst_type == "SWAP"
    assert sync_funding_args.command == "sync-funding-rates"
    assert sync_funding_args.symbol == "BTC-USDT-SWAP"
    assert sync_funding_args.limit == 2
    assert live_sync_args.command == "live-sync"
    assert live_sync_args.symbol == ["BTC-USDT-SWAP"]
    assert live_sync_args.max_messages == 1
    assert live_sync_args.public_only is True


class FakeGateway:
    def __init__(self) -> None:
        self.instrument_calls: list[str] = []
        self.candle_calls: list[dict] = []
        self.rest_positions: list[dict] = []
        self.rest_orders: list[dict] = []
        self.public_ws = OKXWebSocketClient(OKXWebSocketConfig())
        self.private_ws = OKXWebSocketClient(
            OKXWebSocketConfig(api_key="key", secret_key="secret", passphrase="pass")
        )

    def instruments(self, inst_type: str = "SWAP") -> list[Instrument]:
        self.instrument_calls.append(inst_type)
        return [
            Instrument(
                symbol="BTC-USDT-SWAP",
                inst_type="SWAP",
                tick_size=Decimal("0.1"),
                lot_size=Decimal("0.01"),
                min_size=Decimal("0.01"),
                state="live",
            )
        ]

    def history_candles(
        self,
        symbol: str,
        timeframe: str = "1m",
        *,
        after: str | None = None,
        before: str | None = None,
        limit: int = 300,
    ) -> list[Candle]:
        self.candle_calls.append(
            {"symbol": symbol, "timeframe": timeframe, "after": after, "before": before, "limit": limit}
        )
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=start + timedelta(minutes=i),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal(100 + i),
                volume=Decimal("10"),
                confirmed=True,
            )
            for i in range(3)
        ]

    def history_candles_range(
        self, symbol: str, timeframe: str, start_at: datetime, end_at: datetime
    ) -> list[Candle]:
        return [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=start_at + timedelta(minutes=i),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal(100 + i),
                volume=Decimal("10"),
                confirmed=True,
            )
            for i in range(int((end_at - start_at).total_seconds() // 60) + 1)
        ]

    def funding_rate_history(self, symbol: str, *, before: str | None = None, after: str | None = None, limit: int = 100):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return [
            FundingRate(
                symbol=symbol,
                funding_time=start + timedelta(hours=8 * i),
                funding_rate=Decimal("0.0001"),
                realized_rate=Decimal("0.00008"),
            )
            for i in range(limit)
        ]

    def positions(self) -> dict:
        return {"data": self.rest_positions}

    def orders_pending(self) -> dict:
        return {"data": self.rest_orders}


def test_run_instruments_command_uses_gateway() -> None:
    gateway = FakeGateway()
    repo = CandleRepository("sqlite:///:memory:")
    services = AppServices(gateway=gateway, candle_repository=repo)
    args = build_parser().parse_args(["instruments", "--inst-type", "SWAP"])

    output = run_command(args, services)

    assert gateway.instrument_calls == ["SWAP"]
    assert "BTC-USDT-SWAP" in output


def test_run_sync_candles_command_persists_gateway_candles() -> None:
    gateway = FakeGateway()
    repo = CandleRepository("sqlite:///:memory:")
    services = AppServices(gateway=gateway, candle_repository=repo)
    args = build_parser().parse_args(
        ["sync-candles", "--symbol", "BTC-USDT-SWAP", "--timeframe", "1m", "--pages", "1"]
    )

    output = run_command(args, services)

    assert "synced 3 candles" in output
    assert len(repo.list_candles("BTC-USDT-SWAP", "1m")) == 3


def test_run_sync_candles_range_command_persists_gateway_range_candles() -> None:
    gateway = FakeGateway()
    repo = CandleRepository("sqlite:///:memory:")
    services = AppServices(gateway=gateway, candle_repository=repo)
    args = build_parser().parse_args(
        [
            "sync-candles-range",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "1m",
            "--start",
            "2024-01-01T00:00:00Z",
            "--end",
            "2024-01-01T00:02:00Z",
        ]
    )

    output = run_command(args, services)

    assert "synced 3 candles" in output
    assert "range=2024-01-01T00:00:00+00:00->2024-01-01T00:02:00+00:00" in output
    assert len(repo.list_candles("BTC-USDT-SWAP", "1m")) == 3


def test_run_candle_state_command_reports_empty_local_data() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(["candle-state", "--symbol", "BTC-USDT-SWAP", "--timeframe", "1m"])

    output = run_command(args, services)

    assert output == "candle_state symbol=BTC-USDT-SWAP timeframe=1m status=empty"


def test_run_candle_state_command_reports_local_coverage_and_gaps() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="1m",
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
                timeframe="1m",
                timestamp=start + timedelta(minutes=2),
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
    args = build_parser().parse_args(["candle-state", "--symbol", "BTC-USDT-SWAP", "--timeframe", "1m"])

    output = run_command(args, services)

    assert "candle_state symbol=BTC-USDT-SWAP timeframe=1m status=ready" in output
    assert "actual_count=2" in output
    assert "missing_ranges=1" in output
    assert "2024-01-01T00:01:00+00:00->2024-01-01T00:01:00+00:00" in output


def test_run_sync_instruments_command_persists_gateway_instruments() -> None:
    gateway = FakeGateway()
    candle_repo = CandleRepository("sqlite:///:memory:")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    services = AppServices(
        gateway=gateway,
        candle_repository=candle_repo,
        instrument_repository=instrument_repo,
    )
    args = build_parser().parse_args(["sync-instruments", "--inst-type", "SWAP"])

    output = run_command(args, services)

    assert "synced 1 instruments" in output
    instrument = instrument_repo.get("BTC-USDT-SWAP")
    assert instrument is not None
    assert instrument.tick_size == Decimal("0.1")


def test_run_sync_funding_rates_command_persists_gateway_rates() -> None:
    gateway = FakeGateway()
    candle_repo = CandleRepository("sqlite:///:memory:")
    funding_repo = FundingRateRepository("sqlite:///:memory:")
    services = AppServices(
        gateway=gateway,
        candle_repository=candle_repo,
        funding_rate_repository=funding_repo,
    )
    args = build_parser().parse_args(["sync-funding-rates", "--symbol", "BTC-USDT-SWAP", "--limit", "2"])

    output = run_command(args, services)

    assert "synced 2 funding rates" in output
    assert len(funding_repo.list_rates("BTC-USDT-SWAP")) == 2


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


def test_run_aggregate_candles_command_writes_target_timeframe() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="1m",
                timestamp=start + timedelta(minutes=i),
                open=Decimal(99 + i),
                high=Decimal(102 + i),
                low=Decimal(98 + i),
                close=Decimal(100 + i),
                volume=Decimal("100"),
                confirmed=True,
            )
            for i in range(30)
        ]
    )
    services = AppServices(gateway=FakeGateway(), candle_repository=repo)
    args = build_parser().parse_args(
        [
            "aggregate-candles",
            "--symbol",
            "BTC-USDT-SWAP",
            "--source-timeframe",
            "1m",
            "--target-timeframe",
            "15m",
        ]
    )

    output = run_command(args, services)

    assert "aggregated 2 candles" in output
    assert len(repo.list_candles("BTC-USDT-SWAP", "15m")) == 2


def test_run_repair_missing_command_uses_gateway_range_fetch() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            Candle(
                symbol="BTC-USDT-SWAP",
                timeframe="1m",
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
                timeframe="1m",
                timestamp=start + timedelta(minutes=2),
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
    args = build_parser().parse_args(
        ["repair-missing", "--symbol", "BTC-USDT-SWAP", "--timeframe", "1m"]
    )

    output = run_command(args, services)

    assert "repaired 1 candles" in output
    assert len(repo.list_candles("BTC-USDT-SWAP", "1m")) == 3


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


def test_run_paper_run_command_remains_compatible() -> None:
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
            for i in range(40)
        ]
    )
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=repo,
        trade_repository=trade_repo,
    )
    args = build_parser().parse_args(["paper-run", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m"])

    output = run_command(args, services)

    assert "paper_run" in output
    assert len(trade_repo.list_fills("cli-paper")) >= 1


def test_run_live_sync_command_updates_public_and_private_state_summary() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    connector = FakeWebSocketConnector(
        [
            FakeWebSocketSession(
                [
                    {
                        "arg": {"channel": "tickers"},
                        "data": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "last": "70000",
                                "ts": "1717200000000",
                            }
                        ],
                    }
                ]
            ),
            FakeWebSocketSession(
                [
                    {
                        "arg": {"channel": "account"},
                        "data": [
                            {
                                "uTime": "1717200001000",
                                "details": [
                                    {
                                        "ccy": "USDT",
                                        "eq": "1000",
                                        "availBal": "900",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            ),
        ]
    )
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        websocket_connector=connector,
        live_state_repository=live_repo,
    )
    args = build_parser().parse_args(
        ["live-sync", "--symbol", "BTC-USDT-SWAP", "--max-messages", "1"]
    )

    output = run_command(args, services)

    assert "live_sync mode=both" in output
    assert "symbols=BTC-USDT-SWAP" in output
    assert "public_messages=1" in output
    assert "private_messages=1" in output
    assert "tickers=1" in output
    assert "balances=1" in output
    assert "persisted=true" in output
    assert "trading_enabled=false" in output
    restored = live_repo.load_snapshot(account_id="okx_sub_main")
    assert restored.tickers["BTC-USDT-SWAP"].last_price == Decimal("70000")
    assert restored.balances["USDT"].equity == Decimal("1000")
    assert connector.urls == [
        "wss://ws.okx.com:8443/ws/v5/public",
        "wss://ws.okx.com:8443/ws/v5/private",
    ]


def test_run_live_sync_command_public_only_skips_private_connection() -> None:
    connector = FakeWebSocketConnector(
        [
            FakeWebSocketSession(
                [
                    {
                        "arg": {"channel": "tickers"},
                        "data": [
                            {
                                "instId": "ETH-USDT-SWAP",
                                "last": "3000",
                                "ts": "1717200000000",
                            }
                        ],
                    }
                ]
            )
        ]
    )
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        websocket_connector=connector,
    )
    args = build_parser().parse_args(
        ["live-sync", "--symbol", "ETH-USDT-SWAP", "--max-messages", "1", "--public-only"]
    )

    output = run_command(args, services)

    assert "live_sync mode=public" in output
    assert "public_messages=1" in output
    assert "private_messages=0" in output
    assert "persisted=false" in output
    assert len(connector.urls) == 1


def test_run_live_sync_command_rejects_conflicting_modes() -> None:
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        websocket_connector=FakeWebSocketConnector([]),
    )
    args = build_parser().parse_args(["live-sync", "--public-only", "--private-only"])

    try:
        run_command(args, services)
    except ValueError as exc:
        assert "cannot be used together" in str(exc)
    else:
        raise AssertionError("expected conflicting live-sync modes to be rejected")


def test_run_live_reconcile_command_reports_clean_snapshot() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}]
    gateway.rest_orders = [{"ordId": "okx-1"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    live_store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    live_repo.save_snapshot(account_id="okx_sub_main", store=live_store)
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
    )
    args = build_parser().parse_args(["live-reconcile", "--account-id", "okx_sub_main"])

    output = run_command(args, services)

    assert output == (
        "live_reconcile status=clean position_issues=0 "
        "missing_orders_on_exchange=0 missing_orders_locally=0 trading_allowed=true"
    )


def test_run_live_reconcile_command_blocks_on_snapshot_mismatch() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "short", "pos": "-0.2"}]
    gateway.rest_orders = [{"ordId": "exchange-only"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    live_store = live_store_with_position_and_order(order_id="local-only", direction="long", size="0.1")
    live_repo.save_snapshot(account_id="okx_sub_main", store=live_store)
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
    )
    args = build_parser().parse_args(["live-reconcile"])

    output = run_command(args, services)

    assert "live_reconcile status=blocked" in output
    assert "position_issues=2" in output
    assert "missing_orders_on_exchange=1" in output
    assert "missing_orders_locally=1" in output
    assert "trading_allowed=false" in output


def test_run_emergency_pause_and_resume_commands_persist_manual_state() -> None:
    safety_repo = SafetyRepository("sqlite:///:memory:")
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        safety_repository=safety_repo,
    )

    pause_output = run_command(
        build_parser().parse_args(["emergency-pause", "--reason", "operator_stop"]),
        services,
    )
    resume_output = run_command(
        build_parser().parse_args(["emergency-resume", "--reason", "operator_resume"]),
        services,
    )

    assert "emergency_pause account_id=okx_sub_main paused=true" in pause_output
    assert "trading_allowed=false" in pause_output
    assert "emergency_resume account_id=okx_sub_main paused=false" in resume_output
    assert safety_repo.get_pause(account_id="okx_sub_main").paused is False


def test_run_trading_gate_command_allows_clean_state() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    _add_usdt_balance(store)
    live_repo.save_snapshot(account_id="okx_sub_main", store=store)
    gateway.rest_orders = [{"ordId": "okx-1"}]
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )

    output = run_command(build_parser().parse_args(["trading-gate"]), services)

    assert "trading_gate status=allowed" in output
    assert "reason=all_checks_passed" in output
    assert "equity_risk=within_equity_limits" in output
    assert "trading_allowed=true" in output


def test_run_trading_gate_command_blocks_when_manually_paused() -> None:
    safety_repo = SafetyRepository("sqlite:///:memory:")
    safety_repo.set_pause(account_id="okx_sub_main", paused=True, reason="manual")
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=LiveStateRepository("sqlite:///:memory:"),
        safety_repository=safety_repo,
    )

    output = run_command(build_parser().parse_args(["trading-gate"]), services)

    assert "trading_gate status=blocked" in output
    assert "reason=manual_pause" in output
    assert "manual_paused=true" in output
    assert "trading_allowed=false" in output


def test_run_trading_gate_command_blocks_on_reconciliation_mismatch() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "short", "pos": "-0.2"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    store = live_store_with_position_and_order(order_id="local-only", direction="long", size="0.1")
    _add_usdt_balance(store)
    live_repo.save_snapshot(account_id="okx_sub_main", store=store)
    gateway.rest_orders = [{"ordId": "exchange-only"}]
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )

    output = run_command(build_parser().parse_args(["trading-gate"]), services)

    assert "trading_gate status=blocked" in output
    assert "reason=reconciliation_blocked" in output
    assert "position_issues=2" in output
    assert "missing_orders_on_exchange=1" in output
    assert "missing_orders_locally=1" in output
    assert "trading_allowed=false" in output


def test_run_trading_gate_command_blocks_without_equity_snapshot() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    live_repo.save_snapshot(
        account_id="okx_sub_main",
        store=live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1"),
    )
    gateway.rest_orders = [{"ordId": "okx-1"}]
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )

    output = run_command(build_parser().parse_args(["trading-gate"]), services)

    assert "trading_gate status=blocked" in output
    assert "reason=missing_equity_snapshot" in output
    assert "equity_risk=missing_equity_snapshot" in output
    assert "trading_allowed=false" in output


def _add_usdt_balance(store) -> None:
    store.upsert_balance(
        AccountBalance(
            currency="USDT",
            equity=Decimal("1000"),
            available=Decimal("900"),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
    )
