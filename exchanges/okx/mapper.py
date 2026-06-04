from __future__ import annotations

from decimal import Decimal

from core.models import Candle, Fill, FundingRate, IndexPrice, Instrument, MarkPrice, utc_from_ms


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


def map_mark_price(row: dict) -> MarkPrice:
    return MarkPrice(
        symbol=row["instId"],
        mark_price=Decimal(row["markPx"]),
        updated_at=utc_from_ms(row["ts"]),
    )


def map_index_price(row: dict) -> IndexPrice:
    return IndexPrice(
        index_id=row["instId"],
        index_price=Decimal(row["idxPx"]),
        updated_at=utc_from_ms(row["ts"]),
    )


def map_trade_fill(
    row: dict,
    *,
    account_id: str,
    bot_id: str = "live_sync",
    strategy_id: str = "exchange_sync",
    run_id: str = "live",
) -> Fill:
    order_id = str(row.get("ordId") or "")
    created_at = utc_from_ms(row["ts"])
    fill_size = Decimal(row["fillSz"])
    return Fill(
        account_id=account_id,
        bot_id=bot_id,
        strategy_id=strategy_id,
        symbol=row["instId"],
        run_id=run_id,
        fill_id=_trade_fill_id(row, order_id=order_id, created_at=created_at, fill_size=fill_size),
        client_order_id=_client_order_id(row, order_id),
        side=row.get("side") or "unknown",
        size=fill_size,
        price=Decimal(row["fillPx"]),
        fee=Decimal(row.get("fee") or "0"),
        created_at=created_at,
    )


def _trade_fill_id(row: dict, *, order_id: str, created_at, fill_size: Decimal) -> str:
    trade_id = row.get("tradeId")
    if trade_id not in {None, ""}:
        return str(trade_id)
    timestamp_ms = int(created_at.timestamp() * 1000)
    return f"{order_id}:{timestamp_ms}:{fill_size}"


def _client_order_id(row: dict, order_id: str) -> str:
    client_order_id = row.get("clOrdId")
    if client_order_id in {None, "", "0"}:
        return order_id
    return str(client_order_id)
