from __future__ import annotations

from core.models import Candle, Signal


class BaseStrategy:
    account_id: str
    bot_id: str
    strategy_id: str
    symbol: str
    run_id: str
    timeframe: str

    def on_candles(self, context: dict, candles: list[Candle]) -> list[Signal]:
        return []

