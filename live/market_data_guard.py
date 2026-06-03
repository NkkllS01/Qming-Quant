from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class LiveMarketDataResult:
    status: str
    reason: str
    checked_symbols: tuple[str, ...]
    stale_symbols: tuple[str, ...] = ()
    missing_symbols: tuple[str, ...] = ()

    @property
    def trading_allowed(self) -> bool:
        return self.status == "allowed"


class LiveMarketDataGuard:
    def __init__(
        self,
        *,
        mark_price_repository: object,
        symbols: list[str] | tuple[str, ...],
        max_mark_price_age_seconds: int = 120,
        now: datetime | None = None,
    ) -> None:
        if max_mark_price_age_seconds < 0:
            raise ValueError("max_mark_price_age_seconds must be non-negative")
        self.mark_price_repository = mark_price_repository
        self.symbols = tuple(symbols)
        self.max_mark_price_age = timedelta(seconds=max_mark_price_age_seconds)
        self.now = now

    def evaluate(self) -> LiveMarketDataResult:
        if not self.symbols:
            return LiveMarketDataResult(
                status="blocked",
                reason="missing_market_data_symbols",
                checked_symbols=(),
            )

        now = self._now()
        stale_symbols: list[str] = []
        missing_symbols: list[str] = []

        for symbol in self.symbols:
            mark_price = self.mark_price_repository.get(symbol)
            if mark_price is None:
                missing_symbols.append(symbol)
                continue
            updated_at = _ensure_utc(mark_price.updated_at)
            if now - updated_at > self.max_mark_price_age:
                stale_symbols.append(symbol)

        if missing_symbols:
            return LiveMarketDataResult(
                status="blocked",
                reason="missing_mark_price",
                checked_symbols=self.symbols,
                missing_symbols=tuple(missing_symbols),
                stale_symbols=tuple(stale_symbols),
            )
        if stale_symbols:
            return LiveMarketDataResult(
                status="blocked",
                reason="stale_mark_price",
                checked_symbols=self.symbols,
                stale_symbols=tuple(stale_symbols),
            )
        return LiveMarketDataResult(
            status="allowed",
            reason="market_data_fresh",
            checked_symbols=self.symbols,
        )

    def _now(self) -> datetime:
        if self.now is not None:
            return _ensure_utc(self.now)
        return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
