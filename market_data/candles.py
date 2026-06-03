from __future__ import annotations

from datetime import datetime, timedelta

from core.models import Candle


TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
}


def timeframe_delta(timeframe: str) -> timedelta:
    try:
        return timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe: {timeframe}") from exc


def find_missing_ranges(candles: list[Candle], timeframe: str) -> list[tuple[datetime, datetime]]:
    if len(candles) < 2:
        return []
    step = timeframe_delta(timeframe)
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    missing: list[tuple[datetime, datetime]] = []
    for previous, current in zip(ordered, ordered[1:]):
        expected = previous.timestamp + step
        if current.timestamp > expected:
            missing.append((expected, current.timestamp - step))
    return missing


def aggregate_candles(candles: list[Candle], target_timeframe: str) -> list[Candle]:
    if not candles:
        return []
    target_step = timeframe_delta(target_timeframe)
    source = sorted(candles, key=lambda candle: candle.timestamp)
    bucket_size = int(target_step.total_seconds() // timeframe_delta(source[0].timeframe).total_seconds())
    if bucket_size <= 0:
        raise ValueError("Target timeframe must be greater than source timeframe")

    aggregated: list[Candle] = []
    for index in range(0, len(source), bucket_size):
        bucket = source[index : index + bucket_size]
        if len(bucket) != bucket_size:
            continue
        aggregated.append(
            Candle(
                symbol=bucket[0].symbol,
                timeframe=target_timeframe,
                timestamp=bucket[0].timestamp,
                open=bucket[0].open,
                high=max(candle.high for candle in bucket),
                low=min(candle.low for candle in bucket),
                close=bucket[-1].close,
                volume=sum((candle.volume for candle in bucket), start=bucket[0].volume * 0),
                confirmed=all(candle.confirmed for candle in bucket),
            )
        )
    return aggregated

