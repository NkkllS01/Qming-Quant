from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import AppServices, build_parser, run_command
from core.models import Candle
from storage.repositories import CandleRepository


SYMBOL = "BTC-USDT-SWAP"


def main() -> None:
    try:
        _run_check()
    except Exception as exc:
        print(f"FAIL data quality check: {exc}")
        raise SystemExit(1) from exc
    print("PASS data quality check")


def _run_check() -> None:
    repo = CandleRepository("sqlite:///:memory:")
    repo.upsert_many(_seed_gap_candles())
    gateway = FakeGateway()
    services = AppServices(
        gateway=gateway,
        candle_repository=repo,
    )

    before = _command(services, ["candle-state", "--symbol", SYMBOL, "--timeframe", "1m"])
    _assert_contains(before, "missing_ranges=1")

    repaired = _command(services, ["repair-missing", "--symbol", SYMBOL, "--timeframe", "1m"])
    _assert_contains(repaired, f"repaired 2 candles for {SYMBOL} 1m")
    _assert_single_gap_repair_call(gateway)

    after = _command(services, ["candle-state", "--symbol", SYMBOL, "--timeframe", "1m"])
    _assert_contains(after, "missing_ranges=0")
    _assert_contains(after, "actual_count=30")

    aggregated = _command(
        services,
        ["aggregate-candles", "--symbol", SYMBOL, "--source-timeframe", "1m", "--target-timeframe", "15m"],
    )
    _assert_contains(aggregated, f"aggregated 2 candles for {SYMBOL} 1m->15m")
    aggregate_state = _command(services, ["candle-state", "--symbol", SYMBOL, "--timeframe", "15m"])
    _assert_contains(aggregate_state, "missing_ranges=0")
    _assert_contains(aggregate_state, "actual_count=2")
    _assert_aggregated_candles(repo)


def _seed_gap_candles() -> list[Candle]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        _candle(start + timedelta(minutes=index), str(100 + index))
        for index in range(30)
        if index not in {10, 11}
    ]


def _candle(timestamp: datetime, close: str) -> Candle:
    price = Decimal(close)
    return Candle(
        symbol=SYMBOL,
        timeframe="1m",
        timestamp=timestamp,
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=Decimal("10"),
        confirmed=True,
    )


def _command(services: AppServices, argv: list[str]) -> str:
    return run_command(build_parser().parse_args(argv), services)


def _assert_contains(output: str, expected: str) -> None:
    if expected not in output:
        raise RuntimeError(f"expected {expected!r} in {output!r}")


class FakeGateway:
    def __init__(self) -> None:
        self.range_calls: list[tuple[str, str, datetime, datetime]] = []

    def history_candles(self, **kwargs) -> list[Candle]:
        return []

    def history_candles_range(
        self,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[Candle]:
        self.range_calls.append((symbol, timeframe, start_at, end_at))
        if symbol != SYMBOL or timeframe != "1m":
            return []
        candles: list[Candle] = []
        current = start_at
        while current <= end_at:
            minute_offset = int((current - datetime(2024, 1, 1, tzinfo=timezone.utc)).total_seconds() // 60)
            candles.append(_candle(current, str(100 + minute_offset)))
            current += timedelta(minutes=1)
        return candles


def _assert_single_gap_repair_call(gateway: FakeGateway) -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    expected = (
        SYMBOL,
        "1m",
        start + timedelta(minutes=10),
        start + timedelta(minutes=11),
    )
    if gateway.range_calls != [expected]:
        raise RuntimeError(f"unexpected gap repair calls: {gateway.range_calls}")


def _assert_aggregated_candles(repo: CandleRepository) -> None:
    candles = repo.list_candles(SYMBOL, "15m")
    if len(candles) != 2:
        raise RuntimeError("expected two 15m aggregated candles")
    first, second = candles
    if first.open != Decimal("100") or first.high != Decimal("115") or first.low != Decimal("99"):
        raise RuntimeError(f"unexpected first 15m OHLC: {first}")
    if first.close != Decimal("114") or first.volume != Decimal("150"):
        raise RuntimeError(f"unexpected first 15m close/volume: {first}")
    if second.open != Decimal("115") or second.high != Decimal("130") or second.low != Decimal("114"):
        raise RuntimeError(f"unexpected second 15m OHLC: {second}")
    if second.close != Decimal("129") or second.volume != Decimal("150"):
        raise RuntimeError(f"unexpected second 15m close/volume: {second}")


if __name__ == "__main__":
    main()
