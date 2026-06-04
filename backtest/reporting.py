from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.cli_parsing import parse_cli_datetime
from app.serialization import json_ready
from app.services import AppServices
from core.models import Candle, Instrument
from market_data.data_gate import DataGateResult


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
