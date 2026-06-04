from __future__ import annotations

import argparse
import asyncio

from app.cli_parsing import parse_cli_decimal
from app.commands.live_format import live_sync_output, trading_gate_output
from app.commands.runtime import record_runtime_event
from app.live_readiness import evaluate_prelive_readiness
from app.live_services import build_trading_gate, evaluate_cli_trading_gate
from app.services import AppServices
from core.models import OrderIntent
from live.bot import LiveBotConfig, LiveBotLoop
from live.execution import LiveOrderExecutionService
from live.fill_sync import LiveFillSyncService
from live.reconcile import LiveReconciliationService
from live.sync import LiveSyncService


def register(subparsers: argparse._SubParsersAction) -> None:
    sync_fills = subparsers.add_parser("sync-fills", help="Sync recent OKX private fills into local live state")
    sync_fills.add_argument("--account-id", default="okx_sub_main")
    sync_fills.add_argument("--inst-type", default="SWAP")
    sync_fills.add_argument("--symbol", default=None)
    sync_fills.add_argument("--order-id", default=None)
    sync_fills.add_argument("--limit", type=int, default=100)
    sync_fills.set_defaults(handler=handle_sync_fills)

    live_sync = subparsers.add_parser("live-sync", help="Manually run read-only OKX live state sync")
    live_sync.add_argument("--symbol", action="append", default=[])
    live_sync.add_argument("--account-id", default="okx_sub_main")
    live_sync.add_argument("--max-messages", type=int, default=1)
    live_sync.add_argument("--public-only", action="store_true")
    live_sync.add_argument("--private-only", action="store_true")
    live_sync.add_argument("--include-fills-channel", action="store_true")
    live_sync.set_defaults(handler=handle_live_sync)

    live_bot_once = subparsers.add_parser("live-bot-once", help="Run one read-only live bot sync and safety pass")
    live_bot_once.add_argument("--symbol", action="append", default=[])
    live_bot_once.add_argument("--account-id", default="okx_sub_main")
    live_bot_once.add_argument("--max-messages", type=int, default=1)
    live_bot_once.add_argument("--include-fills-channel", action="store_true")
    live_bot_once.add_argument("--skip-gate", action="store_true")
    live_bot_once.set_defaults(handler=handle_live_bot_once)

    live_reconcile = subparsers.add_parser("live-reconcile", help="Compare local live snapshot with OKX REST state")
    live_reconcile.add_argument("--account-id", default="okx_sub_main")
    live_reconcile.set_defaults(handler=handle_live_reconcile)

    trading_gate = subparsers.add_parser("trading-gate", help="Evaluate live trading safety gate")
    trading_gate.add_argument("--account-id", default="okx_sub_main")
    trading_gate.set_defaults(handler=handle_trading_gate)

    live_order_check = subparsers.add_parser("live-order-check", help="Dry-run a live order intent without placing it")
    live_order_check.add_argument("--account-id", default="okx_sub_main")
    live_order_check.add_argument("--bot-id", default="okx_perp_bot_main")
    live_order_check.add_argument("--strategy-id", default="manual_live_check")
    live_order_check.add_argument("--symbol", required=True)
    live_order_check.add_argument("--side", required=True, choices=["buy", "sell"])
    live_order_check.add_argument("--position-action", required=True, choices=["open", "close", "reduce"])
    live_order_check.add_argument("--order-type", default="market", choices=["market", "limit"])
    live_order_check.add_argument("--size", required=True)
    live_order_check.add_argument("--price", default=None)
    live_order_check.add_argument("--reduce-only", action="store_true")
    live_order_check.add_argument("--client-order-id", default="manual-live-check")
    live_order_check.set_defaults(handler=handle_live_order_check)

    prelive_readiness = subparsers.add_parser("prelive-readiness", help="Check local pre-live readiness")
    prelive_readiness.add_argument("--account-id", default="okx_sub_main")
    prelive_readiness.add_argument("--symbol", action="append", default=[])
    prelive_readiness.set_defaults(handler=handle_prelive_readiness)


def handle_sync_fills(args: argparse.Namespace, services: AppServices) -> str:
    if services.live_state_repository is None:
        raise RuntimeError("Live state repository is not configured")
    service = LiveFillSyncService(
        gateway=services.gateway,
        repository=services.live_state_repository,
        account_id=args.account_id,
    )
    result = service.run(
        inst_type=args.inst_type,
        symbol=args.symbol,
        order_id=args.order_id,
        limit=args.limit,
    )
    scope = args.symbol or args.order_id or args.inst_type
    output = (
        f"sync_fills scope={scope} fetched={result.fetched_count} "
        f"stored={result.stored_count} matched_orders={result.matched_count}"
    )
    record_runtime_event(
        services,
        command=args.command,
        outcome="completed",
        details={
            "account_id": args.account_id,
            "scope": scope,
            "fetched": result.fetched_count,
            "stored": result.stored_count,
            "matched_orders": result.matched_count,
        },
    )
    return output


def handle_live_sync(args: argparse.Namespace, services: AppServices) -> str:
    if args.public_only and args.private_only:
        raise ValueError("public-only and private-only cannot be used together")
    connector = services.websocket_connector
    if connector is None:
        raise RuntimeError("OKX WebSocket connector is not configured")
    symbols = args.symbol or ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    service = LiveSyncService(
        gateway=services.gateway,
        connector=connector,
        account_id=args.account_id,
        symbols=symbols,
        repository=services.live_state_repository,
        include_fills_channel=args.include_fills_channel,
    )
    result = asyncio.run(
        service.run_once(
            include_public=not args.private_only,
            include_private=not args.public_only,
            max_messages_per_connection=args.max_messages,
        )
    )
    mode = "both"
    if args.public_only:
        mode = "public"
    elif args.private_only:
        mode = "private"
    output = live_sync_output(
        mode=mode,
        symbols=symbols,
        public_messages=result.public_messages,
        private_messages=result.private_messages,
        tickers_count=result.tickers_count,
        balances_count=result.balances_count,
        positions_count=result.positions_count,
        orders_count=result.orders_count,
        fills_count=result.fills_count,
        fills_channel=args.include_fills_channel,
        persisted=result.persisted,
        trading_enabled=result.trading_enabled,
    )
    record_runtime_event(
        services,
        command=args.command,
        outcome="completed",
        details={
            "mode": mode,
            "symbols": symbols,
            "public_messages": result.public_messages,
            "private_messages": result.private_messages,
            "fills_channel": args.include_fills_channel,
            "persisted": result.persisted,
            "trading_enabled": result.trading_enabled,
        },
    )
    return output


def handle_live_bot_once(args: argparse.Namespace, services: AppServices) -> str:
    connector = services.websocket_connector
    if connector is None:
        raise RuntimeError("OKX WebSocket connector is not configured")
    if services.live_state_repository is None:
        raise RuntimeError("Live state repository is not configured")
    if services.safety_repository is None:
        raise RuntimeError("Safety repository is not configured")
    symbols = args.symbol or services.default_symbols or ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    result = LiveBotLoop(
        config=LiveBotConfig(
            account_id=args.account_id,
            symbols=symbols,
            include_fills_channel=args.include_fills_channel,
            max_messages_per_connection=args.max_messages,
            evaluate_gate=not args.skip_gate,
        ),
        gateway=services.gateway,
        connector=connector,
        live_state_repository=services.live_state_repository,
        safety_repository=services.safety_repository,
        mark_price_repository=services.mark_price_repository,
        runtime_logger=services.runtime_logger,
        max_daily_loss=services.max_daily_loss,
        max_total_drawdown=services.max_total_drawdown_pause,
        max_mark_price_age_seconds=services.max_mark_price_age_seconds,
    ).run_once()
    gate_status = result.gate.status if result.gate is not None else "skipped"
    gate_reason = result.gate.reason if result.gate is not None else "skipped"
    return (
        f"live_bot_once symbols={','.join(symbols)} "
        f"public_messages={result.sync.public_messages} "
        f"private_messages={result.sync.private_messages} "
        f"tickers={result.sync.tickers_count} "
        f"balances={result.sync.balances_count} "
        f"positions={result.sync.positions_count} "
        f"orders={result.sync.orders_count} "
        f"fills={result.sync.fills_count} "
        f"fills_channel={str(args.include_fills_channel).lower()} "
        f"persisted={str(result.sync.persisted).lower()} "
        f"gate_status={gate_status} gate_reason={gate_reason} "
        f"trading_allowed={str(result.gate.trading_allowed if result.gate is not None else False).lower()}"
    )


def handle_live_reconcile(args: argparse.Namespace, services: AppServices) -> str:
    if services.live_state_repository is None:
        raise RuntimeError("Live state repository is not configured")
    service = LiveReconciliationService(
        gateway=services.gateway,
        repository=services.live_state_repository,
        account_id=args.account_id,
    )
    result = service.run()
    output = (
        f"live_reconcile status={result.status} "
        f"position_issues={len(result.positions_issues)} "
        f"missing_orders_on_exchange={len(result.missing_orders_on_exchange)} "
        f"missing_orders_locally={len(result.missing_orders_locally)} "
        f"trading_allowed={str(result.is_clean).lower()}"
    )
    record_runtime_event(
        services,
        command=args.command,
        outcome=result.status,
        details={
            "account_id": args.account_id,
            "position_issues": len(result.positions_issues),
            "missing_orders_on_exchange": len(result.missing_orders_on_exchange),
            "missing_orders_locally": len(result.missing_orders_locally),
            "trading_allowed": result.is_clean,
        },
    )
    return output


def handle_prelive_readiness(args: argparse.Namespace, services: AppServices) -> str:
    symbols = args.symbol or services.default_symbols or ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    result = evaluate_prelive_readiness(services, account_id=args.account_id, symbols=symbols)
    return (
        f"prelive_readiness status={result['status']} "
        f"account_id={args.account_id} symbols={','.join(symbols)} "
        f"manual_paused={str(result['manual_paused']).lower()} "
        f"runtime_log={result['runtime_log']} "
        f"instruments={result['instruments']} "
        f"mark_prices={result['mark_prices']} "
        f"balance_snapshot={result['balance_snapshot']} "
        f"issues={','.join(result['issues']) if result['issues'] else 'none'}"
    )


def handle_trading_gate(args: argparse.Namespace, services: AppServices) -> str:
    result = evaluate_cli_trading_gate(
        services,
        account_id=args.account_id,
        symbols=services.default_symbols or ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
    )
    position_issues = len(result.reconciliation.positions_issues) if result.reconciliation is not None else 0
    missing_orders_on_exchange = (
        len(result.reconciliation.missing_orders_on_exchange) if result.reconciliation is not None else 0
    )
    missing_orders_locally = (
        len(result.reconciliation.missing_orders_locally) if result.reconciliation is not None else 0
    )
    output = trading_gate_output(
        status=result.status,
        reason=result.reason,
        manual_paused=result.pause_state.paused,
        equity_risk=result.equity_risk.reason if result.equity_risk is not None else "not_checked",
        market_data=result.market_data.reason if result.market_data is not None else "not_checked",
        position_issues=position_issues,
        missing_orders_on_exchange=missing_orders_on_exchange,
        missing_orders_locally=missing_orders_locally,
        trading_allowed=result.trading_allowed,
    )
    record_runtime_event(
        services,
        command=args.command,
        outcome=result.status,
        details={
            "account_id": args.account_id,
            "reason": result.reason,
            "manual_paused": result.pause_state.paused,
            "position_issues": position_issues,
            "missing_orders_on_exchange": missing_orders_on_exchange,
            "missing_orders_locally": missing_orders_locally,
            "trading_allowed": result.trading_allowed,
        },
    )
    return output


def handle_live_order_check(args: argparse.Namespace, services: AppServices) -> str:
    if services.live_state_repository is None:
        raise RuntimeError("Live state repository is not configured")
    if services.safety_repository is None:
        raise RuntimeError("Safety repository is not configured")
    intent = OrderIntent(
        account_id=args.account_id,
        bot_id=args.bot_id,
        strategy_id=args.strategy_id,
        symbol=args.symbol,
        run_id="live-check",
        side=args.side,
        position_action=args.position_action,
        order_type=args.order_type,
        size=parse_cli_decimal(args.size, field_name="size"),
        price=parse_cli_decimal(args.price, field_name="price") if args.price is not None else None,
        reduce_only=args.reduce_only,
        client_order_id=args.client_order_id,
    )
    gate = build_trading_gate(services, account_id=args.account_id, symbols=[args.symbol])
    result = LiveOrderExecutionService(
        gateway=services.gateway,
        trading_gate=gate,
        live_state_repository=services.live_state_repository,
        instrument_repository=services.instrument_repository,
    ).check_order(intent)
    gate_reason = result.trading_gate.reason if result.trading_gate is not None else "not_checked"
    market_data_reason = (
        result.trading_gate.market_data.reason
        if result.trading_gate is not None and result.trading_gate.market_data is not None
        else "not_checked"
    )
    output = (
        f"live_order_check status={result.status} reason={result.reason} "
        f"policy={result.policy.reason} gate={gate_reason} market_data={market_data_reason} "
        f"symbol={intent.symbol} side={intent.side} action={intent.position_action} "
        f"order_type={intent.order_type} size={intent.size} reduce_only={str(intent.reduce_only).lower()} "
        f"trading_allowed={str(result.allowed).lower()}"
    )
    record_runtime_event(
        services,
        command=args.command,
        outcome=result.status,
        details={
            "account_id": args.account_id,
            "bot_id": args.bot_id,
            "strategy_id": args.strategy_id,
            "symbol": intent.symbol,
            "side": intent.side,
            "position_action": intent.position_action,
            "order_type": intent.order_type,
            "size": intent.size,
            "reduce_only": intent.reduce_only,
            "reason": result.reason,
            "policy": result.policy.reason,
            "gate": gate_reason,
            "market_data": market_data_reason,
            "trading_allowed": result.allowed,
        },
    )
    return output

