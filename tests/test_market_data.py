from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.models import Candle, FundingRate, IndexPrice, Instrument, MarkPrice
from market_data.candle_sync import CandleSyncService
from market_data.candles import aggregate_candles, find_missing_ranges
from storage.repositories import (
    CandleRepository,
    FundingRateRepository,
    IndexPriceRepository,
    InstrumentRepository,
    MarkPriceRepository,
)


def _candle(ts: datetime, close: str, timeframe: str = "1m") -> Candle:
    price = Decimal(close)
    return Candle(
        symbol="BTC-USDT-SWAP",
        timeframe=timeframe,
        timestamp=ts,
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=Decimal("10"),
        confirmed=True,
    )


def test_find_missing_ranges_detects_time_gap() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        _candle(start, "100"),
        _candle(start + timedelta(minutes=1), "101"),
        _candle(start + timedelta(minutes=4), "104"),
    ]

    missing = find_missing_ranges(candles, timeframe="1m")

    assert missing == [
        (
            start + timedelta(minutes=2),
            start + timedelta(minutes=3),
        )
    ]


def test_aggregate_1m_candles_to_15m_bucket() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [_candle(start + timedelta(minutes=i), str(100 + i)) for i in range(15)]

    aggregated = aggregate_candles(candles, target_timeframe="15m")

    assert len(aggregated) == 1
    result = aggregated[0]
    assert result.timeframe == "15m"
    assert result.timestamp == start
    assert result.open == Decimal("100")
    assert result.high == Decimal("115")
    assert result.low == Decimal("99")
    assert result.close == Decimal("114")
    assert result.volume == Decimal("150")


def test_candle_repository_upserts_by_symbol_timeframe_timestamp() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many([_candle(ts, "100")])
    repo.upsert_many([_candle(ts, "101")])

    candles = repo.list_candles("BTC-USDT-SWAP", "1m")

    assert len(candles) == 1
    assert candles[0].close == Decimal("101")


def test_candle_repository_tracks_sync_state_and_time_range() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many([_candle(start + timedelta(minutes=i), str(100 + i)) for i in range(5)])

    state = repo.get_sync_state("BTC-USDT-SWAP", "1m")
    selected = repo.list_candles(
        "BTC-USDT-SWAP",
        "1m",
        start=start + timedelta(minutes=1),
        end=start + timedelta(minutes=3),
    )

    assert state is not None
    assert state.first_ts == start
    assert state.last_ts == start + timedelta(minutes=4)
    assert state.actual_count == 5
    assert [c.close for c in selected] == [Decimal("101"), Decimal("102"), Decimal("103")]


def test_instrument_repository_upserts_and_reads_instrument_specs() -> None:
    repo = InstrumentRepository("sqlite:///:memory:")
    repo.upsert_many(
        [
            Instrument(
                symbol="BTC-USDT-SWAP",
                inst_type="SWAP",
                base_currency="BTC",
                quote_currency="USDT",
                settle_currency="USDT",
                tick_size=Decimal("0.1"),
                lot_size=Decimal("0.01"),
                min_size=Decimal("0.01"),
                contract_value=Decimal("0.01"),
                state="live",
            )
        ]
    )
    repo.upsert_many(
        [
            Instrument(
                symbol="BTC-USDT-SWAP",
                inst_type="SWAP",
                base_currency="BTC",
                quote_currency="USDT",
                settle_currency="USDT",
                tick_size=Decimal("0.01"),
                lot_size=Decimal("0.001"),
                min_size=Decimal("0.001"),
                contract_value=Decimal("0.01"),
                state="live",
            )
        ]
    )

    instrument = repo.get("BTC-USDT-SWAP")
    instruments = repo.list_instruments(inst_type="SWAP")

    assert instrument is not None
    assert instrument.tick_size == Decimal("0.01")
    assert instrument.lot_size == Decimal("0.001")
    assert instrument.min_size == Decimal("0.001")
    assert len(instruments) == 1


def test_funding_rate_repository_upserts_and_reads_by_time_range() -> None:
    repo = FundingRateRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            FundingRate(
                symbol="BTC-USDT-SWAP",
                funding_time=start,
                funding_rate=Decimal("0.0001"),
                realized_rate=Decimal("0.00008"),
            ),
            FundingRate(
                symbol="BTC-USDT-SWAP",
                funding_time=start + timedelta(hours=8),
                funding_rate=Decimal("-0.0002"),
                realized_rate=Decimal("-0.00018"),
            ),
        ]
    )
    repo.upsert_many(
        [
            FundingRate(
                symbol="BTC-USDT-SWAP",
                funding_time=start,
                funding_rate=Decimal("0.0003"),
                realized_rate=Decimal("0.00025"),
            )
        ]
    )

    rows = repo.list_rates(
        "BTC-USDT-SWAP",
        start=start,
        end=start + timedelta(hours=1),
    )

    assert len(rows) == 1
    assert rows[0].funding_rate == Decimal("0.0003")
    assert rows[0].realized_rate == Decimal("0.00025")


def test_mark_price_repository_upserts_and_reads_latest_snapshot() -> None:
    repo = MarkPriceRepository("sqlite:///:memory:")
    first = datetime(2024, 1, 1, tzinfo=timezone.utc)
    second = first + timedelta(seconds=1)
    repo.upsert_many(
        [
            MarkPrice(symbol="BTC-USDT-SWAP", mark_price=Decimal("70000.1"), updated_at=first),
            MarkPrice(symbol="ETH-USDT-SWAP", mark_price=Decimal("3000.2"), updated_at=first),
        ]
    )
    repo.upsert_many(
        [
            MarkPrice(symbol="BTC-USDT-SWAP", mark_price=Decimal("70001.3"), updated_at=second),
        ]
    )

    btc = repo.get("BTC-USDT-SWAP")
    rows = repo.list_prices()

    assert btc is not None
    assert btc.mark_price == Decimal("70001.3")
    assert btc.updated_at == second
    assert [row.symbol for row in rows] == ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]


def test_index_price_repository_upserts_and_reads_latest_snapshot() -> None:
    repo = IndexPriceRepository("sqlite:///:memory:")
    first = datetime(2024, 1, 1, tzinfo=timezone.utc)
    second = first + timedelta(seconds=1)
    repo.upsert_many(
        [
            IndexPrice(index_id="BTC-USDT", index_price=Decimal("69990.1"), updated_at=first),
            IndexPrice(index_id="ETH-USDT", index_price=Decimal("2995.2"), updated_at=first),
        ]
    )
    repo.upsert_many(
        [
            IndexPrice(index_id="BTC-USDT", index_price=Decimal("69991.3"), updated_at=second),
        ]
    )

    btc = repo.get("BTC-USDT")
    rows = repo.list_prices()

    assert btc is not None
    assert btc.index_price == Decimal("69991.3")
    assert btc.updated_at == second
    assert [row.index_id for row in rows] == ["BTC-USDT", "ETH-USDT"]


def test_candle_sync_repairs_missing_ranges_with_fetcher() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many(
        [
            _candle(start, "100"),
            _candle(start + timedelta(minutes=1), "101"),
            _candle(start + timedelta(minutes=4), "104"),
        ]
    )
    calls: list[tuple[datetime, datetime]] = []

    def fetch_range(symbol: str, timeframe: str, start_at: datetime, end_at: datetime):
        calls.append((start_at, end_at))
        return [
            _candle(start + timedelta(minutes=2), "102"),
            _candle(start + timedelta(minutes=3), "103"),
        ]

    service = CandleSyncService(fetch_page=lambda **_: [], store=repo, fetch_range=fetch_range)

    repaired = service.repair_missing_ranges("BTC-USDT-SWAP", "1m")

    assert repaired == 2
    assert calls == [(start + timedelta(minutes=2), start + timedelta(minutes=3))]
    assert len(repo.list_candles("BTC-USDT-SWAP", "1m")) == 5


def test_candle_sync_syncs_explicit_time_range_with_fetcher() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    calls: list[tuple[str, str, datetime, datetime]] = []

    def fetch_range(symbol: str, timeframe: str, start_at: datetime, end_at: datetime):
        calls.append((symbol, timeframe, start_at, end_at))
        return [
            _candle(start_at, "100"),
            _candle(end_at, "101"),
        ]

    service = CandleSyncService(fetch_page=lambda **_: [], store=repo, fetch_range=fetch_range)

    synced = service.sync_range("BTC-USDT-SWAP", "1m", start, start + timedelta(minutes=1))

    assert synced == 2
    assert calls == [("BTC-USDT-SWAP", "1m", start, start + timedelta(minutes=1))]
    assert len(repo.list_candles("BTC-USDT-SWAP", "1m")) == 2


def test_candle_sync_aggregates_source_timeframe_into_target_timeframe() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.upsert_many([_candle(start + timedelta(minutes=i), str(100 + i)) for i in range(30)])
    service = CandleSyncService(fetch_page=lambda **_: [], store=repo)

    written = service.aggregate_and_store("BTC-USDT-SWAP", "1m", "15m")

    aggregated = repo.list_candles("BTC-USDT-SWAP", "15m")
    assert written == 2
    assert len(aggregated) == 2
    assert aggregated[0].close == Decimal("114")
    assert aggregated[1].close == Decimal("129")
