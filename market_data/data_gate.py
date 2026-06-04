from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.models import Candle
from market_data.candles import find_missing_ranges


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
