from decimal import Decimal
from datetime import datetime, timedelta, timezone

from tests.cli_fakes import FakeGateway
from app.main import AppServices, build_parser, run_command
from core.models import Candle
from storage.repositories import (
    CandleRepository,
    FundingRateRepository,
    IndexPriceRepository,
    InstrumentRepository,
    MarkPriceRepository,
)




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


def test_run_sync_mark_prices_command_persists_gateway_prices() -> None:
    gateway = FakeGateway()
    candle_repo = CandleRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    services = AppServices(
        gateway=gateway,
        candle_repository=candle_repo,
        mark_price_repository=mark_repo,
    )
    args = build_parser().parse_args(["sync-mark-prices", "--symbol", "BTC-USDT-SWAP"])

    output = run_command(args, services)

    assert "synced 1 mark prices for BTC-USDT-SWAP" in output
    price = mark_repo.get("BTC-USDT-SWAP")
    assert price is not None
    assert price.mark_price == Decimal("70000.12")


def test_run_sync_index_prices_command_persists_gateway_prices() -> None:
    gateway = FakeGateway()
    candle_repo = CandleRepository("sqlite:///:memory:")
    index_repo = IndexPriceRepository("sqlite:///:memory:")
    services = AppServices(
        gateway=gateway,
        candle_repository=candle_repo,
        index_price_repository=index_repo,
    )
    args = build_parser().parse_args(["sync-index-prices", "--quote-currency", "USDT"])

    output = run_command(args, services)

    assert "synced 1 index prices for USDT" in output
    price = index_repo.get("BTC-USDT")
    assert price is not None
    assert price.index_price == Decimal("69990.12")


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
