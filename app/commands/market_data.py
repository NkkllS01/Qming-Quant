from __future__ import annotations

import argparse

from app.cli_parsing import parse_cli_datetime
from app.services import AppServices
from market_data.candle_sync import CandleSyncService


def register(subparsers: argparse._SubParsersAction) -> None:
    instruments = subparsers.add_parser("instruments", help="List OKX instruments")
    instruments.add_argument("--inst-type", default="SWAP")
    instruments.set_defaults(handler=handle_instruments)

    sync_instruments = subparsers.add_parser("sync-instruments", help="Sync OKX instruments locally")
    sync_instruments.add_argument("--inst-type", default="SWAP")
    sync_instruments.set_defaults(handler=handle_sync_instruments)

    sync_funding = subparsers.add_parser("sync-funding-rates", help="Sync OKX funding rates locally")
    sync_funding.add_argument("--symbol", required=True)
    sync_funding.add_argument("--before", default=None)
    sync_funding.add_argument("--after", default=None)
    sync_funding.add_argument("--limit", type=int, default=100)
    sync_funding.set_defaults(handler=handle_sync_funding_rates)

    sync_mark = subparsers.add_parser("sync-mark-prices", help="Sync OKX mark price snapshots locally")
    sync_mark.add_argument("--inst-type", default="SWAP")
    sync_mark.add_argument("--symbol", default=None)
    sync_mark.set_defaults(handler=handle_sync_mark_prices)

    sync_index = subparsers.add_parser("sync-index-prices", help="Sync OKX index price snapshots locally")
    sync_index.add_argument("--quote-currency", default=None)
    sync_index.add_argument("--index-id", default=None)
    sync_index.set_defaults(handler=handle_sync_index_prices)

    sync = subparsers.add_parser("sync-candles", help="Sync historical candles")
    sync.add_argument("--symbol", required=True)
    sync.add_argument("--timeframe", default="1m")
    sync.add_argument("--pages", type=int, default=1)
    sync.set_defaults(handler=handle_sync_candles)

    sync_range = subparsers.add_parser("sync-candles-range", help="Sync historical candles by time range")
    sync_range.add_argument("--symbol", required=True)
    sync_range.add_argument("--timeframe", default="1m")
    sync_range.add_argument("--start", required=True)
    sync_range.add_argument("--end", required=True)
    sync_range.set_defaults(handler=handle_sync_candles_range)

    candle_state = subparsers.add_parser("candle-state", help="Show local candle coverage and gaps")
    candle_state.add_argument("--symbol", required=True)
    candle_state.add_argument("--timeframe", default="1m")
    candle_state.set_defaults(handler=handle_candle_state)

    repair = subparsers.add_parser("repair-missing", help="Repair missing local candle ranges")
    repair.add_argument("--symbol", required=True)
    repair.add_argument("--timeframe", default="1m")
    repair.set_defaults(handler=handle_repair_missing)

    aggregate = subparsers.add_parser("aggregate-candles", help="Aggregate local candles")
    aggregate.add_argument("--symbol", required=True)
    aggregate.add_argument("--source-timeframe", default="1m")
    aggregate.add_argument("--target-timeframe", default="15m")
    aggregate.set_defaults(handler=handle_aggregate_candles)


def handle_instruments(args: argparse.Namespace, services: AppServices) -> str:
    instruments = services.gateway.instruments(args.inst_type)
    return "\n".join(
        f"{instrument.symbol} {instrument.inst_type} tick={instrument.tick_size} "
        f"lot={instrument.lot_size} state={instrument.state}"
        for instrument in instruments
    )


def handle_sync_candles(args: argparse.Namespace, services: AppServices) -> str:
    sync = CandleSyncService(fetch_page=services.gateway.history_candles, store=services.candle_repository)
    count = sync.sync_history(args.symbol, args.timeframe, pages=args.pages)
    return f"synced {count} candles for {args.symbol} {args.timeframe}"


def handle_sync_candles_range(args: argparse.Namespace, services: AppServices) -> str:
    sync = CandleSyncService(
        fetch_page=services.gateway.history_candles,
        store=services.candle_repository,
        fetch_range=services.gateway.history_candles_range,
    )
    start_at = parse_cli_datetime(args.start)
    end_at = parse_cli_datetime(args.end)
    count = sync.sync_range(args.symbol, args.timeframe, start_at, end_at)
    return (
        f"synced {count} candles for {args.symbol} {args.timeframe} "
        f"range={start_at.isoformat()}->{end_at.isoformat()}"
    )


def handle_candle_state(args: argparse.Namespace, services: AppServices) -> str:
    state = services.candle_repository.refresh_sync_state(args.symbol, args.timeframe)
    if state is None:
        return f"candle_state symbol={args.symbol} timeframe={args.timeframe} status=empty"
    missing_preview = ",".join(
        f"{start.isoformat()}->{end.isoformat()}" for start, end in state.missing_ranges[:3]
    )
    return (
        f"candle_state symbol={args.symbol} timeframe={args.timeframe} status=ready "
        f"first={state.first_ts.isoformat()} last={state.last_ts.isoformat()} "
        f"actual_count={state.actual_count} missing_ranges={len(state.missing_ranges)} "
        f"missing_preview={missing_preview or 'none'}"
    )


def handle_sync_instruments(args: argparse.Namespace, services: AppServices) -> str:
    instruments = services.gateway.instruments(args.inst_type)
    if services.instrument_repository is not None:
        services.instrument_repository.upsert_many(instruments)
    return f"synced {len(instruments)} instruments for {args.inst_type}"


def handle_sync_funding_rates(args: argparse.Namespace, services: AppServices) -> str:
    rates = services.gateway.funding_rate_history(
        args.symbol,
        before=args.before,
        after=args.after,
        limit=args.limit,
    )
    if services.funding_rate_repository is not None:
        services.funding_rate_repository.upsert_many(rates)
    return f"synced {len(rates)} funding rates for {args.symbol}"


def handle_sync_mark_prices(args: argparse.Namespace, services: AppServices) -> str:
    prices = services.gateway.mark_prices(args.inst_type, symbol=args.symbol)
    if services.mark_price_repository is not None:
        services.mark_price_repository.upsert_many(prices)
    scope = args.symbol if args.symbol is not None else args.inst_type
    return f"synced {len(prices)} mark prices for {scope}"


def handle_sync_index_prices(args: argparse.Namespace, services: AppServices) -> str:
    prices = services.gateway.index_tickers(quote_currency=args.quote_currency, index_id=args.index_id)
    if services.index_price_repository is not None:
        services.index_price_repository.upsert_many(prices)
    scope = args.index_id or args.quote_currency or "all"
    return f"synced {len(prices)} index prices for {scope}"


def handle_repair_missing(args: argparse.Namespace, services: AppServices) -> str:
    sync = CandleSyncService(
        fetch_page=services.gateway.history_candles,
        store=services.candle_repository,
        fetch_range=services.gateway.history_candles_range,
    )
    count = sync.repair_missing_ranges(args.symbol, args.timeframe)
    return f"repaired {count} candles for {args.symbol} {args.timeframe}"


def handle_aggregate_candles(args: argparse.Namespace, services: AppServices) -> str:
    sync = CandleSyncService(fetch_page=services.gateway.history_candles, store=services.candle_repository)
    count = sync.aggregate_and_store(args.symbol, args.source_timeframe, args.target_timeframe)
    return f"aggregated {count} candles for {args.symbol} {args.source_timeframe}->{args.target_timeframe}"
