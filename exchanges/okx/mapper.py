from __future__ import annotations

from decimal import Decimal

from core.models import Candle, FundingRate, Instrument, utc_from_ms


def map_okx_candles(
    symbol: str,
    timeframe: str,
    rows: list[list[str]],
    *,
    confirmed_only: bool = True,
) -> list[Candle]:
    candles = [Candle.from_okx_row(symbol, timeframe, row) for row in rows]
    if confirmed_only:
        return [candle for candle in candles if candle.confirmed]
    return candles


def map_instrument(row: dict) -> Instrument:
    return Instrument(
        symbol=row["instId"],
        inst_type=row["instType"],
        base_currency=row.get("baseCcy") or None,
        quote_currency=row.get("quoteCcy") or None,
        settle_currency=row.get("settleCcy") or None,
        tick_size=Decimal(row["tickSz"]),
        lot_size=Decimal(row["lotSz"]),
        min_size=Decimal(row["minSz"]),
        contract_value=Decimal(row["ctVal"]) if row.get("ctVal") else None,
        state=row["state"],
    )


def map_funding_rate(row: dict) -> FundingRate:
    return FundingRate(
        symbol=row["instId"],
        funding_time=utc_from_ms(row["fundingTime"]),
        funding_rate=Decimal(row["fundingRate"]),
        realized_rate=Decimal(row["realizedRate"]) if row.get("realizedRate") else None,
    )
