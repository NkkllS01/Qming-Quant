from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.cli_parsing import parse_cli_datetime, parse_cli_decimal
from app.commands.runtime import record_runtime_event
from app.serialization import json_ready
from app.services import AppServices
from backtest.engine import BacktestEngine
from core.models import Candle, Instrument
from market_data.candles import find_missing_ranges
from simulation.engine import SimulationTradingEngine
from strategies.base import BaseStrategy
from strategies.examples.ma_crossover import MovingAverageCrossoverStrategy
from strategies.examples.trend import MultiTimeframeTrendStrategy


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


def build_cli_strategy(strategy_name: str, *, symbol: str, timeframe: str, run_id: str) -> BaseStrategy:
    symbol_prefix = symbol.split("-")[0].lower()
    if strategy_name == "ma-crossover":
        return MovingAverageCrossoverStrategy(
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id=f"{symbol_prefix}_ma_crossover_{timeframe}",
            symbol=symbol,
            run_id=run_id,
            timeframe=timeframe,
        )
    return MultiTimeframeTrendStrategy(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id=f"{symbol_prefix}_trend_{timeframe}",
        symbol=symbol,
        run_id=run_id,
        timeframe=timeframe,
    )


def write_backtest_report(
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
        "metrics": json_ready(result.metrics.model_dump()),
        "trades": json_ready([trade.model_dump() for trade in result.trades]),
        "equity_curve": json_ready([point.model_dump() for point in result.equity_curve]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def write_backtest_blocked_report(
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


def report_context_window(
    candles: list[Candle],
    start: str | None,
    end: str | None,
) -> tuple[datetime | None, datetime | None]:
    start_at = parse_cli_datetime(start) if start is not None else (candles[0].timestamp if candles else None)
    end_at = parse_cli_datetime(end) if end is not None else (candles[-1].timestamp if candles else None)
    return start_at, end_at


def build_funding_context(
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


def evaluate_candle_data_gate(
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
