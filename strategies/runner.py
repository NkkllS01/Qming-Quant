from __future__ import annotations

from core.models import Candle, Signal
from strategies.base import BaseStrategy


class StrategyRunner:
    def __init__(self, strategy: BaseStrategy) -> None:
        self.strategy = strategy

    def run_on_candles(self, candles: list[Candle], context: dict | None = None) -> list[Signal]:
        return self.strategy.on_candles(context or {}, candles)

