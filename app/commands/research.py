from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path

from app.cli_parsing import parse_cli_datetime, parse_cli_decimal
from app.commands.runtime import record_runtime_event
from app.services import AppServices
from backtest.engine import BacktestEngine
from backtest.reporting import (
    build_funding_context,
    report_context_window,
    write_backtest_blocked_report,
    write_backtest_report,
)
from core.models import Candle, Instrument
from market_data.data_gate import evaluate_candle_data_gate
from simulation.engine import SimulationTradingEngine
from strategies.factory import build_cli_strategy


def register(subparsers: argparse._SubParsersAction) -> None:
    backtest = subparsers.add_parser("backtest", help="Run the first trend strategy backtest")
    backtest.add_argument("--symbol", default="BTC-USDT-SWAP")
    backtest.add_argument("--timeframe", default="15m")
    backtest.add_argument("--allow-gaps", action="store_true")
    backtest.add_argument("--min-candles", type=int, default=30)
    backtest.add_argument("--start", default=None)
    backtest.add_argument("--end", default=None)
    backtest.add_argument("--report-json", default=None)
    backtest.add_argument("--strategy", default="trend", choices=["trend", "ma-crossover"])
    backtest.set_defaults(handler=handle_backtest)

    sim = subparsers.add_parser("sim-run", help="Run the starter strategy through local simulation")
    sim.add_argument("--symbol", default="BTC-USDT-SWAP")
    sim.add_argument("--timeframe", default="15m")
    sim.add_argument("--allow-gaps", action="store_true")
    sim.add_argument("--min-candles", type=int, default=30)
    sim.add_argument("--start", default=None)
    sim.add_argument("--end", default=None)
    sim.add_argument("--strategy", default="trend", choices=["trend", "ma-crossover"])
    sim.add_argument("--current-daily-loss", default="0")
    sim.add_argument("--current-drawdown", default="0")
    sim.set_defaults(handler=handle_sim_run)


def handle_backtest(args: argparse.Namespace, services: AppServices) -> str:
    candles = list_command_candles(services, args.symbol, args.timeframe, args.start, args.end)
    gate = evaluate_candle_data_gate(
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
            funding_context = build_funding_context(
                services,
                args.symbol,
                *report_context_window(candles, args.start, args.end),
            )
            write_backtest_blocked_report(
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
    strategy = build_cli_strategy(args.strategy, symbol=args.symbol, timeframe=args.timeframe, run_id="cli-backtest")
    instrument = instrument_or_default(services, args.symbol)
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
        funding_context = build_funding_context(
            services,
            args.symbol,
            *report_context_window(candles, args.start, args.end),
        )
        write_backtest_report(
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
        f"symbol={args.symbol} timeframe={args.timeframe} strategy={args.strategy} "
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


def handle_sim_run(args: argparse.Namespace, services: AppServices) -> str:
    run_id = "cli-sim"
    output_prefix = "sim_run"
    candles = list_command_candles(services, args.symbol, args.timeframe, args.start, args.end)
    gate = evaluate_candle_data_gate(
        args.symbol,
        args.timeframe,
        candles,
        allow_gaps=args.allow_gaps,
        min_candles=args.min_candles,
    )
    if gate.status == "blocked":
        record_runtime_event(
            services,
            command=args.command,
            outcome="blocked",
            details={
                "symbol": args.symbol,
                "timeframe": args.timeframe,
                "reason": gate.reason,
                "candle_count": gate.candle_count,
            },
        )
        return f"{output_prefix} {gate.to_cli()}"
    strategy = build_cli_strategy(args.strategy, symbol=args.symbol, timeframe=args.timeframe, run_id=run_id)
    instrument = instrument_or_default(services, args.symbol)
    result = SimulationTradingEngine(
        initial_equity=Decimal("1000"),
        max_risk_per_trade=services.max_risk_per_trade,
        max_daily_loss=services.max_daily_loss,
        max_total_drawdown_pause=services.max_total_drawdown_pause,
        max_open_positions=services.max_open_positions,
        current_daily_loss=parse_cli_decimal(args.current_daily_loss, field_name="current-daily-loss"),
        current_drawdown=parse_cli_decimal(args.current_drawdown, field_name="current-drawdown"),
        tick_size=instrument.tick_size,
        lot_size=instrument.lot_size,
        min_size=instrument.min_size,
        fill_id_prefix="sim",
    ).run(strategy, candles)
    persisted = False
    if services.trade_repository is not None:
        services.trade_repository.save_simulation_run(
            run_id=run_id,
            fills=result.fills,
            positions=result.positions,
            journal=result.journal,
        )
        persisted = True
    output = (
        f"{output_prefix} symbol={args.symbol} timeframe={args.timeframe} strategy={args.strategy} "
        f"start={args.start or 'all'} end={args.end or 'all'} "
        f"tick_size={instrument.tick_size} lot_size={instrument.lot_size} "
        f"min_size={instrument.min_size} "
        f"max_risk_per_trade={services.max_risk_per_trade} "
        f"max_open_positions={services.max_open_positions} "
        f"signals={result.signals_count} approved={result.approved_count} "
        f"rejected={result.rejected_count} fills={result.fills_count} "
        f"positions={result.positions_count} final_equity={result.final_equity} "
        f"persisted={str(persisted).lower()}"
    )
    record_runtime_event(
        services,
        command=args.command,
        outcome="completed",
        details={
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "strategy": args.strategy,
            "signals": result.signals_count,
            "approved": result.approved_count,
            "rejected": result.rejected_count,
            "fills": result.fills_count,
            "positions": result.positions_count,
            "final_equity": result.final_equity,
            "persisted": persisted,
        },
    )
    return output


def instrument_or_default(services: AppServices, symbol: str) -> Instrument:
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


def list_command_candles(
    services: AppServices,
    symbol: str,
    timeframe: str,
    start: str | None,
    end: str | None,
) -> list[Candle]:
    start_at = parse_cli_datetime(start) if start is not None else None
    end_at = parse_cli_datetime(end) if end is not None else None
    if start_at is not None and end_at is not None and end_at < start_at:
        raise ValueError("end must be greater than or equal to start")
    return services.candle_repository.list_candles(symbol, timeframe, start=start_at, end=end_at)

