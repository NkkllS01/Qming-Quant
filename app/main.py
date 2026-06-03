from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.config import Settings
from backtest.engine import BacktestEngine
from core.models import Candle, Instrument
from exchanges.okx.gateway import OKXGateway
from exchanges.okx.rest import OKXRestClient
from exchanges.okx.websocket import OKXWebSocketClient, OKXWebSocketConfig, WebsocketsConnector
from live.reconcile import LiveReconciliationService
from live.sync import LiveSyncService
from live.trading_gate import TradingGateService
from market_data.candle_sync import CandleSyncService
from market_data.candles import find_missing_ranges
from paper.engine import PaperTradingEngine
from storage.live_repository import LiveStateRepository
from storage.repositories import CandleRepository, FundingRateRepository, InstrumentRepository
from storage.safety_repository import SafetyRepository
from storage.trade_repository import TradeRepository
from strategies.examples.trend import MultiTimeframeTrendStrategy


@dataclass
class AppServices:
    gateway: object
    candle_repository: CandleRepository
    instrument_repository: InstrumentRepository | None = None
    funding_rate_repository: FundingRateRepository | None = None
    trade_repository: TradeRepository | None = None
    websocket_connector: object | None = None
    live_state_repository: LiveStateRepository | None = None
    safety_repository: SafetyRepository | None = None


@dataclass
class DataGateResult:
    status: str
    reason: str
    symbol: str
    timeframe: str
    candle_count: int
    allow_gaps: bool
    min_candles: int
    missing_ranges_count: int = 0
    first_missing: tuple[datetime, datetime] | None = None

    def to_cli(self) -> str:
        if self.status == "passed":
            return (
                f"data_gate status=passed symbol={self.symbol} timeframe={self.timeframe} "
                f"actual_count={self.candle_count} min_candles={self.min_candles}"
            )
        if self.reason == "missing_candles" and self.first_missing is not None:
            return (
                f"data_gate status=blocked reason=missing_candles symbol={self.symbol} "
                f"timeframe={self.timeframe} missing_ranges={self.missing_ranges_count} "
                f"first_missing={self.first_missing[0].isoformat()}->{self.first_missing[1].isoformat()}"
            )
        if self.reason == "insufficient_candles":
            return (
                f"data_gate status=blocked reason=insufficient_candles symbol={self.symbol} "
                f"timeframe={self.timeframe} actual_count={self.candle_count} "
                f"min_candles={self.min_candles}"
            )
        return f"data_gate status=blocked reason={self.reason} symbol={self.symbol} timeframe={self.timeframe}"

    def to_report(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "candle_count": self.candle_count,
            "allow_gaps": self.allow_gaps,
            "min_candles": self.min_candles,
            "missing_ranges": self.missing_ranges_count,
            "first_missing": (
                {
                    "start": self.first_missing[0].isoformat(),
                    "end": self.first_missing[1].isoformat(),
                }
                if self.first_missing is not None
                else None
            ),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trade", description="OKX contract quant trading CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    instruments = subparsers.add_parser("instruments", help="List OKX instruments")
    instruments.add_argument("--inst-type", default="SWAP")

    sync_instruments = subparsers.add_parser("sync-instruments", help="Sync OKX instruments locally")
    sync_instruments.add_argument("--inst-type", default="SWAP")

    sync_funding = subparsers.add_parser("sync-funding-rates", help="Sync OKX funding rates locally")
    sync_funding.add_argument("--symbol", required=True)
    sync_funding.add_argument("--before", default=None)
    sync_funding.add_argument("--after", default=None)
    sync_funding.add_argument("--limit", type=int, default=100)

    sync = subparsers.add_parser("sync-candles", help="Sync historical candles")
    sync.add_argument("--symbol", required=True)
    sync.add_argument("--timeframe", default="1m")
    sync.add_argument("--pages", type=int, default=1)

    sync_range = subparsers.add_parser("sync-candles-range", help="Sync historical candles by time range")
    sync_range.add_argument("--symbol", required=True)
    sync_range.add_argument("--timeframe", default="1m")
    sync_range.add_argument("--start", required=True)
    sync_range.add_argument("--end", required=True)

    candle_state = subparsers.add_parser("candle-state", help="Show local candle coverage and gaps")
    candle_state.add_argument("--symbol", required=True)
    candle_state.add_argument("--timeframe", default="1m")

    backtest = subparsers.add_parser("backtest", help="Run the first trend strategy backtest")
    backtest.add_argument("--symbol", default="BTC-USDT-SWAP")
    backtest.add_argument("--timeframe", default="15m")
    backtest.add_argument("--allow-gaps", action="store_true")
    backtest.add_argument("--min-candles", type=int, default=30)
    backtest.add_argument("--start", default=None)
    backtest.add_argument("--end", default=None)
    backtest.add_argument("--report-json", default=None)

    sim = subparsers.add_parser("sim-run", help="Run the starter strategy through local simulation")
    sim.add_argument("--symbol", default="BTC-USDT-SWAP")
    sim.add_argument("--timeframe", default="15m")
    sim.add_argument("--allow-gaps", action="store_true")
    sim.add_argument("--min-candles", type=int, default=30)
    sim.add_argument("--start", default=None)
    sim.add_argument("--end", default=None)

    paper = subparsers.add_parser("paper-run", help="Compatibility alias for sim-run")
    paper.add_argument("--symbol", default="BTC-USDT-SWAP")
    paper.add_argument("--timeframe", default="15m")
    paper.add_argument("--allow-gaps", action="store_true")
    paper.add_argument("--min-candles", type=int, default=30)
    paper.add_argument("--start", default=None)
    paper.add_argument("--end", default=None)

    repair = subparsers.add_parser("repair-missing", help="Repair missing local candle ranges")
    repair.add_argument("--symbol", required=True)
    repair.add_argument("--timeframe", default="1m")

    aggregate = subparsers.add_parser("aggregate-candles", help="Aggregate local candles")
    aggregate.add_argument("--symbol", required=True)
    aggregate.add_argument("--source-timeframe", default="1m")
    aggregate.add_argument("--target-timeframe", default="15m")

    live_sync = subparsers.add_parser("live-sync", help="Manually run read-only OKX live state sync")
    live_sync.add_argument("--symbol", action="append", default=[])
    live_sync.add_argument("--account-id", default="okx_sub_main")
    live_sync.add_argument("--max-messages", type=int, default=1)
    live_sync.add_argument("--public-only", action="store_true")
    live_sync.add_argument("--private-only", action="store_true")

    live_reconcile = subparsers.add_parser("live-reconcile", help="Compare local live snapshot with OKX REST state")
    live_reconcile.add_argument("--account-id", default="okx_sub_main")

    trading_gate = subparsers.add_parser("trading-gate", help="Evaluate live trading safety gate")
    trading_gate.add_argument("--account-id", default="okx_sub_main")

    emergency_pause = subparsers.add_parser("emergency-pause", help="Manually block live trading")
    emergency_pause.add_argument("--account-id", default="okx_sub_main")
    emergency_pause.add_argument("--reason", default="manual_emergency_pause")

    emergency_resume = subparsers.add_parser("emergency-resume", help="Clear manual live trading pause")
    emergency_resume.add_argument("--account-id", default="okx_sub_main")
    emergency_resume.add_argument("--reason", default="manual_resume")

    return parser


def build_services(settings: Settings | None = None) -> AppServices:
    settings = settings or Settings.from_env()
    rest = OKXRestClient(
        api_key=settings.okx_api_key,
        secret_key=settings.okx_secret_key,
        passphrase=settings.okx_passphrase,
    )
    public_ws = OKXWebSocketClient(OKXWebSocketConfig())
    private_ws = OKXWebSocketClient(
        OKXWebSocketConfig(
            api_key=settings.okx_api_key,
            secret_key=settings.okx_secret_key,
            passphrase=settings.okx_passphrase,
        )
    )
    return AppServices(
        gateway=OKXGateway(rest, public_ws=public_ws, private_ws=private_ws),
        candle_repository=CandleRepository(settings.database_url),
        instrument_repository=InstrumentRepository(settings.database_url),
        funding_rate_repository=FundingRateRepository(settings.database_url),
        trade_repository=TradeRepository(settings.database_url),
        websocket_connector=WebsocketsConnector(),
        live_state_repository=LiveStateRepository(settings.database_url),
        safety_repository=SafetyRepository(settings.database_url),
    )


def run_command(args: argparse.Namespace, services: AppServices) -> str:
    if args.command == "instruments":
        instruments = services.gateway.instruments(args.inst_type)
        return "\n".join(
            f"{instrument.symbol} {instrument.inst_type} tick={instrument.tick_size} "
            f"lot={instrument.lot_size} state={instrument.state}"
            for instrument in instruments
        )
    if args.command == "sync-candles":
        sync = CandleSyncService(
            fetch_page=services.gateway.history_candles,
            store=services.candle_repository,
        )
        count = sync.sync_history(
            args.symbol,
            args.timeframe,
            pages=args.pages,
        )
        return f"synced {count} candles for {args.symbol} {args.timeframe}"
    if args.command == "sync-candles-range":
        sync = CandleSyncService(
            fetch_page=services.gateway.history_candles,
            store=services.candle_repository,
            fetch_range=services.gateway.history_candles_range,
        )
        start_at = _parse_cli_datetime(args.start)
        end_at = _parse_cli_datetime(args.end)
        count = sync.sync_range(args.symbol, args.timeframe, start_at, end_at)
        return (
            f"synced {count} candles for {args.symbol} {args.timeframe} "
            f"range={start_at.isoformat()}->{end_at.isoformat()}"
        )
    if args.command == "candle-state":
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
    if args.command == "sync-instruments":
        instruments = services.gateway.instruments(args.inst_type)
        if services.instrument_repository is not None:
            services.instrument_repository.upsert_many(instruments)
        return f"synced {len(instruments)} instruments for {args.inst_type}"
    if args.command == "sync-funding-rates":
        rates = services.gateway.funding_rate_history(
            args.symbol,
            before=args.before,
            after=args.after,
            limit=args.limit,
        )
        if services.funding_rate_repository is not None:
            services.funding_rate_repository.upsert_many(rates)
        return f"synced {len(rates)} funding rates for {args.symbol}"
    if args.command == "backtest":
        candles = _list_command_candles(services, args.symbol, args.timeframe, args.start, args.end)
        gate = _evaluate_candle_data_gate(
            args.symbol,
            args.timeframe,
            candles,
            allow_gaps=args.allow_gaps,
            min_candles=args.min_candles,
        )
        if gate.status == "blocked":
            report_path = None
            if args.report_json is not None:
                report_path = Path(args.report_json)
                funding_context = _build_funding_context(
                    services,
                    args.symbol,
                    *_report_context_window(candles, args.start, args.end),
                )
                _write_backtest_blocked_report(
                    report_path,
                    symbol=args.symbol,
                    timeframe=args.timeframe,
                    start=args.start,
                    end=args.end,
                    gate=gate,
                    funding_context=funding_context,
                )
            suffix = f" report_json={report_path}" if report_path is not None else ""
            return f"{gate.to_cli()}{suffix}"
        strategy = MultiTimeframeTrendStrategy(
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id=f"{args.symbol.split('-')[0].lower()}_trend_{args.timeframe}",
            symbol=args.symbol,
            run_id="cli-backtest",
            timeframe=args.timeframe,
        )
        instrument = _instrument_or_default(services, args.symbol)
        result = BacktestEngine(
            initial_equity=Decimal("1000"),
            tick_size=instrument.tick_size,
            lot_size=instrument.lot_size,
            min_size=instrument.min_size,
        ).run(strategy, candles)
        metrics = result.metrics
        report_path = None
        if args.report_json is not None:
            report_path = Path(args.report_json)
            funding_context = _build_funding_context(
                services,
                args.symbol,
                *_report_context_window(candles, args.start, args.end),
            )
            _write_backtest_report(
                report_path,
                symbol=args.symbol,
                timeframe=args.timeframe,
                start=args.start,
                end=args.end,
                allow_gaps=args.allow_gaps,
                min_candles=args.min_candles,
                candle_count=len(candles),
                gate=gate,
                instrument=instrument,
                result=result,
                funding_context=funding_context,
            )
        return (
            f"symbol={args.symbol} timeframe={args.timeframe} "
            f"start={args.start or 'all'} "
            f"end={args.end or 'all'} "
            f"tick_size={instrument.tick_size} "
            f"lot_size={instrument.lot_size} "
            f"min_size={instrument.min_size} "
            f"total_trades={metrics.total_trades} "
            f"final_equity={result.final_equity} "
            f"win_rate={metrics.win_rate:.4f} "
            f"max_drawdown={metrics.max_drawdown} "
            f"profit_factor={metrics.profit_factor} "
            f"payoff_ratio={metrics.payoff_ratio} "
            f"max_consecutive_losses={metrics.max_consecutive_losses} "
            f"average_holding_seconds={metrics.average_holding_seconds} "
            f"total_fees={metrics.total_fees} "
            f"report_json={report_path if report_path is not None else 'none'}"
        )
    if args.command == "repair-missing":
        sync = CandleSyncService(
            fetch_page=services.gateway.history_candles,
            store=services.candle_repository,
            fetch_range=services.gateway.history_candles_range,
        )
        count = sync.repair_missing_ranges(args.symbol, args.timeframe)
        return f"repaired {count} candles for {args.symbol} {args.timeframe}"
    if args.command == "aggregate-candles":
        sync = CandleSyncService(
            fetch_page=services.gateway.history_candles,
            store=services.candle_repository,
        )
        count = sync.aggregate_and_store(
            args.symbol,
            args.source_timeframe,
            args.target_timeframe,
        )
        return (
            f"aggregated {count} candles for {args.symbol} "
            f"{args.source_timeframe}->{args.target_timeframe}"
        )
    if args.command in {"sim-run", "paper-run"}:
        run_id = "cli-sim" if args.command == "sim-run" else "cli-paper"
        output_prefix = "sim_run" if args.command == "sim-run" else "paper_run"
        candles = _list_command_candles(services, args.symbol, args.timeframe, args.start, args.end)
        gate = _evaluate_candle_data_gate(
            args.symbol,
            args.timeframe,
            candles,
            allow_gaps=args.allow_gaps,
            min_candles=args.min_candles,
        )
        if gate.status == "blocked":
            return f"{output_prefix} {gate.to_cli()}"
        strategy = MultiTimeframeTrendStrategy(
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id=f"{args.symbol.split('-')[0].lower()}_trend_{args.timeframe}",
            symbol=args.symbol,
            run_id=run_id,
            timeframe=args.timeframe,
        )
        instrument = _instrument_or_default(services, args.symbol)
        result = PaperTradingEngine(
            initial_equity=Decimal("1000"),
            tick_size=instrument.tick_size,
            lot_size=instrument.lot_size,
            min_size=instrument.min_size,
        ).run(strategy, candles)
        persisted = False
        if services.trade_repository is not None:
            services.trade_repository.save_paper_run(
                run_id=run_id,
                fills=result.fills,
                positions=result.positions,
                journal=result.journal,
            )
            persisted = True
        return (
            f"{output_prefix} symbol={args.symbol} timeframe={args.timeframe} "
            f"start={args.start or 'all'} end={args.end or 'all'} "
            f"tick_size={instrument.tick_size} lot_size={instrument.lot_size} "
            f"min_size={instrument.min_size} "
            f"signals={result.signals_count} approved={result.approved_count} "
            f"rejected={result.rejected_count} fills={result.fills_count} "
            f"positions={result.positions_count} final_equity={result.final_equity} "
            f"persisted={str(persisted).lower()}"
        )
    if args.command == "live-sync":
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
        return (
            f"live_sync mode={mode} symbols={','.join(symbols)} "
            f"public_messages={result.public_messages} "
            f"private_messages={result.private_messages} "
            f"tickers={result.tickers_count} "
            f"balances={result.balances_count} "
            f"positions={result.positions_count} "
            f"orders={result.orders_count} "
            f"persisted={str(result.persisted).lower()} "
            f"trading_enabled={str(result.trading_enabled).lower()}"
        )
    if args.command == "live-reconcile":
        if services.live_state_repository is None:
            raise RuntimeError("Live state repository is not configured")
        service = LiveReconciliationService(
            gateway=services.gateway,
            repository=services.live_state_repository,
            account_id=args.account_id,
        )
        result = service.run()
        return (
            f"live_reconcile status={result.status} "
            f"position_issues={len(result.positions_issues)} "
            f"missing_orders_on_exchange={len(result.missing_orders_on_exchange)} "
            f"missing_orders_locally={len(result.missing_orders_locally)} "
            f"trading_allowed={str(result.is_clean).lower()}"
        )
    if args.command == "emergency-pause":
        if services.safety_repository is None:
            raise RuntimeError("Safety repository is not configured")
        state = services.safety_repository.set_pause(
            account_id=args.account_id,
            paused=True,
            reason=args.reason,
        )
        return (
            f"emergency_pause account_id={state.account_id} paused={str(state.paused).lower()} "
            f"reason={state.reason} trading_allowed=false"
        )
    if args.command == "emergency-resume":
        if services.safety_repository is None:
            raise RuntimeError("Safety repository is not configured")
        state = services.safety_repository.set_pause(
            account_id=args.account_id,
            paused=False,
            reason=args.reason,
        )
        return (
            f"emergency_resume account_id={state.account_id} paused={str(state.paused).lower()} "
            f"reason={state.reason}"
        )
    if args.command == "trading-gate":
        if services.live_state_repository is None:
            raise RuntimeError("Live state repository is not configured")
        if services.safety_repository is None:
            raise RuntimeError("Safety repository is not configured")
        reconciliation = LiveReconciliationService(
            gateway=services.gateway,
            repository=services.live_state_repository,
            account_id=args.account_id,
        )
        result = TradingGateService(
            reconciliation=reconciliation,
            safety_repository=services.safety_repository,
            account_id=args.account_id,
        ).evaluate()
        position_issues = len(result.reconciliation.positions_issues) if result.reconciliation is not None else 0
        missing_orders_on_exchange = (
            len(result.reconciliation.missing_orders_on_exchange) if result.reconciliation is not None else 0
        )
        missing_orders_locally = (
            len(result.reconciliation.missing_orders_locally) if result.reconciliation is not None else 0
        )
        return (
            f"trading_gate status={result.status} reason={result.reason} "
            f"manual_paused={str(result.pause_state.paused).lower()} "
            f"position_issues={position_issues} "
            f"missing_orders_on_exchange={missing_orders_on_exchange} "
            f"missing_orders_locally={missing_orders_locally} "
            f"trading_allowed={str(result.trading_allowed).lower()}"
        )
    raise ValueError(f"Unsupported command: {args.command}")


def _instrument_or_default(services: AppServices, symbol: str) -> Instrument:
    if services.instrument_repository is not None:
        instrument = services.instrument_repository.get(symbol)
        if instrument is not None:
            return instrument
    return Instrument(
        symbol=symbol,
        inst_type="SWAP",
        tick_size=Decimal("0.1"),
        lot_size=Decimal("0.01"),
        min_size=Decimal("0.01"),
        state="unknown",
    )


def _write_backtest_report(
    path: Path,
    *,
    symbol: str,
    timeframe: str,
    start: str | None,
    end: str | None,
    allow_gaps: bool,
    min_candles: int,
    candle_count: int,
    gate: DataGateResult,
    instrument: Instrument,
    result,
    funding_context: dict,
) -> None:
    report = {
        "system": "Qiming Quant",
        "command": "backtest",
        "symbol": symbol,
        "timeframe": timeframe,
        "data_window": {
            "start": start or "all",
            "end": end or "all",
            "candle_count": candle_count,
            "allow_gaps": allow_gaps,
            "min_candles": min_candles,
        },
        "data_gate": gate.to_report(),
        "instrument": {
            "tick_size": str(instrument.tick_size),
            "lot_size": str(instrument.lot_size),
            "min_size": str(instrument.min_size),
        },
        "funding_rates": funding_context,
        "initial_equity": str(result.initial_equity),
        "final_equity": str(result.final_equity),
        "metrics": _json_ready(result.metrics.model_dump()),
        "trades": _json_ready([trade.model_dump() for trade in result.trades]),
        "equity_curve": _json_ready([point.model_dump() for point in result.equity_curve]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_backtest_blocked_report(
    path: Path,
    *,
    symbol: str,
    timeframe: str,
    start: str | None,
    end: str | None,
    gate: DataGateResult,
    funding_context: dict,
) -> None:
    report = {
        "system": "Qiming Quant",
        "command": "backtest",
        "symbol": symbol,
        "timeframe": timeframe,
        "status": "blocked",
        "data_window": {
            "start": start or "all",
            "end": end or "all",
            "candle_count": gate.candle_count,
            "allow_gaps": gate.allow_gaps,
            "min_candles": gate.min_candles,
        },
        "data_gate": gate.to_report(),
        "funding_rates": funding_context,
        "metrics": None,
        "trades": [],
        "equity_curve": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def _json_ready(value):
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _report_context_window(
    candles: list[Candle],
    start: str | None,
    end: str | None,
) -> tuple[datetime | None, datetime | None]:
    start_at = _parse_cli_datetime(start) if start is not None else (candles[0].timestamp if candles else None)
    end_at = _parse_cli_datetime(end) if end is not None else (candles[-1].timestamp if candles else None)
    return start_at, end_at


def _build_funding_context(
    services: AppServices,
    symbol: str,
    start: datetime | None,
    end: datetime | None,
) -> dict:
    if services.funding_rate_repository is None:
        return {
            "status": "unavailable",
            "count": 0,
            "window": {
                "start": start.isoformat() if start is not None else None,
                "end": end.isoformat() if end is not None else None,
            },
        }
    rates = services.funding_rate_repository.list_rates(symbol, start=start, end=end)
    if not rates:
        return {
            "status": "no_data",
            "count": 0,
            "window": {
                "start": start.isoformat() if start is not None else None,
                "end": end.isoformat() if end is not None else None,
            },
            "average_rate": None,
            "min_rate": None,
            "max_rate": None,
            "first_funding_time": None,
            "last_funding_time": None,
        }
    funding_values = [rate.funding_rate for rate in rates]
    average_rate = sum(funding_values, Decimal("0")) / Decimal(len(funding_values))
    return {
        "status": "available",
        "count": len(rates),
        "window": {
            "start": start.isoformat() if start is not None else None,
            "end": end.isoformat() if end is not None else None,
        },
        "average_rate": str(average_rate),
        "min_rate": str(min(funding_values)),
        "max_rate": str(max(funding_values)),
        "first_funding_time": rates[0].funding_time.isoformat(),
        "last_funding_time": rates[-1].funding_time.isoformat(),
    }


def _list_command_candles(
    services: AppServices,
    symbol: str,
    timeframe: str,
    start: str | None,
    end: str | None,
) -> list[Candle]:
    start_at = _parse_cli_datetime(start) if start is not None else None
    end_at = _parse_cli_datetime(end) if end is not None else None
    if start_at is not None and end_at is not None and end_at < start_at:
        raise ValueError("end must be greater than or equal to start")
    return services.candle_repository.list_candles(symbol, timeframe, start=start_at, end=end_at)


def _evaluate_candle_data_gate(
    symbol: str,
    timeframe: str,
    candles: list[Candle],
    *,
    allow_gaps: bool,
    min_candles: int,
) -> DataGateResult:
    if not candles:
        return DataGateResult(
            status="blocked",
            reason="empty",
            symbol=symbol,
            timeframe=timeframe,
            candle_count=0,
            allow_gaps=allow_gaps,
            min_candles=min_candles,
        )
    missing_ranges = find_missing_ranges(candles, timeframe)
    if missing_ranges and not allow_gaps:
        first_missing = missing_ranges[0]
        return DataGateResult(
            status="blocked",
            reason="missing_candles",
            symbol=symbol,
            timeframe=timeframe,
            candle_count=len(candles),
            allow_gaps=allow_gaps,
            min_candles=min_candles,
            missing_ranges_count=len(missing_ranges),
            first_missing=first_missing,
        )
    if len(candles) < min_candles:
        return DataGateResult(
            status="blocked",
            reason="insufficient_candles",
            symbol=symbol,
            timeframe=timeframe,
            candle_count=len(candles),
            allow_gaps=allow_gaps,
            min_candles=min_candles,
        )
    return DataGateResult(
        status="passed",
        reason="ok",
        symbol=symbol,
        timeframe=timeframe,
        candle_count=len(candles),
        allow_gaps=allow_gaps,
        min_candles=min_candles,
        missing_ranges_count=len(missing_ranges),
    )


def _parse_cli_datetime(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    print(run_command(args, build_services()))


if __name__ == "__main__":
    main()
