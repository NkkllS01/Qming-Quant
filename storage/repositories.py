from __future__ import annotations

from decimal import Decimal

from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, Numeric, String, Table, create_engine, select
from sqlalchemy.engine import Engine

from core.models import Candle, CandleSyncState, FundingRate, IndexPrice, Instrument, MarkPrice
from market_data.candles import find_missing_ranges
from storage.db import ensure_utc, upsert_rows


class CandleRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self.candles = Table(
            "candles",
            self.metadata,
            Column("symbol", String, primary_key=True),
            Column("timeframe", String, primary_key=True),
            Column("timestamp", DateTime(timezone=True), primary_key=True),
            Column("open", Numeric(38, 18), nullable=False),
            Column("high", Numeric(38, 18), nullable=False),
            Column("low", Numeric(38, 18), nullable=False),
            Column("close", Numeric(38, 18), nullable=False),
            Column("volume", Numeric(38, 18), nullable=False),
            Column("confirmed", Boolean, nullable=False),
        )
        self.candle_sync_state = Table(
            "candle_sync_state",
            self.metadata,
            Column("symbol", String, primary_key=True),
            Column("timeframe", String, primary_key=True),
            Column("first_ts", DateTime(timezone=True), nullable=False),
            Column("last_ts", DateTime(timezone=True), nullable=False),
            Column("actual_count", Integer, nullable=False),
            Column("missing_ranges", String, nullable=False, default=""),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.metadata.create_all(self.engine)

    def upsert_many(self, candles: list[Candle]) -> None:
        if not candles:
            return
        rows = [
            {
                "symbol": candle.symbol,
                "timeframe": candle.timeframe,
                "timestamp": candle.timestamp,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "confirmed": candle.confirmed,
            }
            for candle in candles
        ]
        with self.engine.begin() as conn:
            upsert_rows(conn, self.candles, rows, ["symbol", "timeframe", "timestamp"])
        self.refresh_sync_state(candles[0].symbol, candles[0].timeframe)

    def list_candles(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Candle]:
        stmt = (
            select(self.candles)
            .where(self.candles.c.symbol == symbol)
            .where(self.candles.c.timeframe == timeframe)
        )
        if start is not None:
            stmt = stmt.where(self.candles.c.timestamp >= start)
        if end is not None:
            stmt = stmt.where(self.candles.c.timestamp <= end)
        stmt = stmt.order_by(self.candles.c.timestamp)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [
            Candle(
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                timestamp=ensure_utc(row["timestamp"]),
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                volume=Decimal(row["volume"]),
                confirmed=row["confirmed"],
            )
            for row in rows
        ]

    def refresh_sync_state(self, symbol: str, timeframe: str) -> CandleSyncState | None:
        candles = self.list_candles(symbol, timeframe)
        if not candles:
            return None
        missing = find_missing_ranges(candles, timeframe)
        state = CandleSyncState(
            symbol=symbol,
            timeframe=timeframe,
            first_ts=candles[0].timestamp,
            last_ts=candles[-1].timestamp,
            actual_count=len(candles),
            missing_ranges=missing,
            updated_at=datetime.now(timezone.utc),
        )
        self.upsert_sync_state(state)
        return state

    def upsert_sync_state(self, state: CandleSyncState) -> None:
        row = {
            "symbol": state.symbol,
            "timeframe": state.timeframe,
            "first_ts": state.first_ts,
            "last_ts": state.last_ts,
            "actual_count": state.actual_count,
            "missing_ranges": _encode_missing_ranges(state.missing_ranges),
            "updated_at": state.updated_at,
        }
        with self.engine.begin() as conn:
            upsert_rows(conn, self.candle_sync_state, [row], ["symbol", "timeframe"])

    def get_sync_state(self, symbol: str, timeframe: str) -> CandleSyncState | None:
        stmt = (
            select(self.candle_sync_state)
            .where(self.candle_sync_state.c.symbol == symbol)
            .where(self.candle_sync_state.c.timeframe == timeframe)
        )
        with self.engine.begin() as conn:
            row = conn.execute(stmt).mappings().first()
        if row is None:
            return None
        return CandleSyncState(
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            first_ts=ensure_utc(row["first_ts"]),
            last_ts=ensure_utc(row["last_ts"]),
            actual_count=row["actual_count"],
            missing_ranges=_decode_missing_ranges(row["missing_ranges"]),
            updated_at=ensure_utc(row["updated_at"]),
        )


class InstrumentRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self.instruments = Table(
            "instruments",
            self.metadata,
            Column("symbol", String, primary_key=True),
            Column("inst_type", String, nullable=False),
            Column("base_currency", String, nullable=True),
            Column("quote_currency", String, nullable=True),
            Column("settle_currency", String, nullable=True),
            Column("tick_size", String, nullable=False),
            Column("lot_size", String, nullable=False),
            Column("min_size", String, nullable=False),
            Column("contract_value", String, nullable=True),
            Column("state", String, nullable=False),
        )
        self.metadata.create_all(self.engine)

    def upsert_many(self, instruments: list[Instrument]) -> None:
        if not instruments:
            return
        rows = [
            {
                "symbol": instrument.symbol,
                "inst_type": instrument.inst_type,
                "base_currency": instrument.base_currency,
                "quote_currency": instrument.quote_currency,
                "settle_currency": instrument.settle_currency,
                "tick_size": str(instrument.tick_size),
                "lot_size": str(instrument.lot_size),
                "min_size": str(instrument.min_size),
                "contract_value": str(instrument.contract_value) if instrument.contract_value is not None else None,
                "state": instrument.state,
            }
            for instrument in instruments
        ]
        with self.engine.begin() as conn:
            upsert_rows(conn, self.instruments, rows, ["symbol"])

    def get(self, symbol: str) -> Instrument | None:
        stmt = select(self.instruments).where(self.instruments.c.symbol == symbol)
        with self.engine.begin() as conn:
            row = conn.execute(stmt).mappings().first()
        return _instrument_from_row(row) if row is not None else None

    def list_instruments(self, *, inst_type: str | None = None) -> list[Instrument]:
        stmt = select(self.instruments)
        if inst_type is not None:
            stmt = stmt.where(self.instruments.c.inst_type == inst_type)
        stmt = stmt.order_by(self.instruments.c.symbol)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_instrument_from_row(row) for row in rows]


class FundingRateRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self.funding_rates = Table(
            "funding_rates",
            self.metadata,
            Column("symbol", String, primary_key=True),
            Column("funding_time", DateTime(timezone=True), primary_key=True),
            Column("funding_rate", String, nullable=False),
            Column("realized_rate", String, nullable=True),
        )
        self.metadata.create_all(self.engine)

    def upsert_many(self, rates: list[FundingRate]) -> None:
        if not rates:
            return
        rows = [
            {
                "symbol": rate.symbol,
                "funding_time": rate.funding_time,
                "funding_rate": str(rate.funding_rate),
                "realized_rate": str(rate.realized_rate) if rate.realized_rate is not None else None,
            }
            for rate in rates
        ]
        with self.engine.begin() as conn:
            upsert_rows(conn, self.funding_rates, rows, ["symbol", "funding_time"])

    def list_rates(
        self,
        symbol: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[FundingRate]:
        stmt = select(self.funding_rates).where(self.funding_rates.c.symbol == symbol)
        if start is not None:
            stmt = stmt.where(self.funding_rates.c.funding_time >= start)
        if end is not None:
            stmt = stmt.where(self.funding_rates.c.funding_time <= end)
        stmt = stmt.order_by(self.funding_rates.c.funding_time)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_funding_rate_from_row(row) for row in rows]


class MarkPriceRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self.mark_prices = Table(
            "mark_prices",
            self.metadata,
            Column("symbol", String, primary_key=True),
            Column("mark_price", String, nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.metadata.create_all(self.engine)

    def upsert_many(self, prices: list[MarkPrice]) -> None:
        if not prices:
            return
        rows = [
            {
                "symbol": price.symbol,
                "mark_price": str(price.mark_price),
                "updated_at": price.updated_at,
            }
            for price in prices
        ]
        with self.engine.begin() as conn:
            upsert_rows(conn, self.mark_prices, rows, ["symbol"])

    def list_prices(self) -> list[MarkPrice]:
        stmt = select(self.mark_prices).order_by(self.mark_prices.c.symbol)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_mark_price_from_row(row) for row in rows]

    def get(self, symbol: str) -> MarkPrice | None:
        stmt = select(self.mark_prices).where(self.mark_prices.c.symbol == symbol)
        with self.engine.begin() as conn:
            row = conn.execute(stmt).mappings().first()
        return _mark_price_from_row(row) if row is not None else None


class IndexPriceRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self.index_prices = Table(
            "index_prices",
            self.metadata,
            Column("index_id", String, primary_key=True),
            Column("index_price", String, nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.metadata.create_all(self.engine)

    def upsert_many(self, prices: list[IndexPrice]) -> None:
        if not prices:
            return
        rows = [
            {
                "index_id": price.index_id,
                "index_price": str(price.index_price),
                "updated_at": price.updated_at,
            }
            for price in prices
        ]
        with self.engine.begin() as conn:
            upsert_rows(conn, self.index_prices, rows, ["index_id"])

    def list_prices(self) -> list[IndexPrice]:
        stmt = select(self.index_prices).order_by(self.index_prices.c.index_id)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_index_price_from_row(row) for row in rows]

    def get(self, index_id: str) -> IndexPrice | None:
        stmt = select(self.index_prices).where(self.index_prices.c.index_id == index_id)
        with self.engine.begin() as conn:
            row = conn.execute(stmt).mappings().first()
        return _index_price_from_row(row) if row is not None else None


def _encode_missing_ranges(ranges: list[tuple[datetime, datetime]]) -> str:
    return ";".join(f"{start.isoformat()}|{end.isoformat()}" for start, end in ranges)


def _decode_missing_ranges(value: str) -> list[tuple[datetime, datetime]]:
    if not value:
        return []
    ranges: list[tuple[datetime, datetime]] = []
    for item in value.split(";"):
        start, end = item.split("|", maxsplit=1)
        ranges.append((ensure_utc(datetime.fromisoformat(start)), ensure_utc(datetime.fromisoformat(end))))
    return ranges


def _instrument_from_row(row) -> Instrument:
    return Instrument(
        symbol=row["symbol"],
        inst_type=row["inst_type"],
        base_currency=row["base_currency"],
        quote_currency=row["quote_currency"],
        settle_currency=row["settle_currency"],
        tick_size=Decimal(row["tick_size"]),
        lot_size=Decimal(row["lot_size"]),
        min_size=Decimal(row["min_size"]),
        contract_value=Decimal(row["contract_value"]) if row["contract_value"] is not None else None,
        state=row["state"],
    )


def _funding_rate_from_row(row) -> FundingRate:
    return FundingRate(
        symbol=row["symbol"],
        funding_time=ensure_utc(row["funding_time"]),
        funding_rate=Decimal(row["funding_rate"]),
        realized_rate=Decimal(row["realized_rate"]) if row["realized_rate"] is not None else None,
    )


def _mark_price_from_row(row) -> MarkPrice:
    return MarkPrice(
        symbol=row["symbol"],
        mark_price=Decimal(row["mark_price"]),
        updated_at=ensure_utc(row["updated_at"]),
    )


def _index_price_from_row(row) -> IndexPrice:
    return IndexPrice(
        index_id=row["index_id"],
        index_price=Decimal(row["index_price"]),
        updated_at=ensure_utc(row["updated_at"]),
    )
