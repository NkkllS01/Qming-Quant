from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from core.models import Candle
from market_data.candles import aggregate_candles


class CandleSyncService:
    def __init__(
        self,
        fetch_page: Callable[..., list[Candle]],
        store,
        fetch_range: Callable[[str, str, datetime, datetime], list[Candle]] | None = None,
    ) -> None:
        self.fetch_page = fetch_page
        self.store = store
        self.fetch_range = fetch_range

    def sync_history(self, symbol: str, timeframe: str, *, pages: int = 1, limit: int = 300) -> int:
        cursor = None
        total = 0
        for _ in range(pages):
            candles = self.fetch_page(symbol=symbol, timeframe=timeframe, after=cursor, limit=limit)
            if not candles:
                break
            self.store.upsert_many(candles)
            total += len(candles)
            cursor = str(int(min(c.timestamp for c in candles).timestamp() * 1000))
        return total

    def sync_range(self, symbol: str, timeframe: str, start_at: datetime, end_at: datetime) -> int:
        if self.fetch_range is None:
            raise ValueError("fetch_range is required to sync a candle range")
        if end_at < start_at:
            raise ValueError("end_at must be greater than or equal to start_at")

        candles = self.fetch_range(symbol, timeframe, start_at, end_at)
        self.store.upsert_many(candles)
        return len(candles)

    def repair_missing_ranges(self, symbol: str, timeframe: str) -> int:
        if self.fetch_range is None:
            raise ValueError("fetch_range is required to repair missing candle ranges")
        state = self.store.refresh_sync_state(symbol, timeframe)
        if state is None:
            return 0
        total = 0
        for start_at, end_at in state.missing_ranges:
            candles = self.fetch_range(symbol, timeframe, start_at, end_at)
            self.store.upsert_many(candles)
            total += len(candles)
        self.store.refresh_sync_state(symbol, timeframe)
        return total

    def aggregate_and_store(self, symbol: str, source_timeframe: str, target_timeframe: str) -> int:
        source = self.store.list_candles(symbol, source_timeframe)
        aggregated = aggregate_candles(source, target_timeframe)
        self.store.upsert_many(aggregated)
        return len(aggregated)
