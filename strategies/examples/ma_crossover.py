from __future__ import annotations

from decimal import Decimal

from core.models import Candle, Signal
from strategies.base import BaseStrategy


class MovingAverageCrossoverStrategy(BaseStrategy):
    def __init__(
        self,
        *,
        account_id: str,
        bot_id: str,
        strategy_id: str,
        symbol: str,
        run_id: str,
        timeframe: str = "15m",
        fast_period: int = 5,
        slow_period: int = 20,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.04,
    ) -> None:
        if fast_period <= 0 or slow_period <= 0 or fast_period >= slow_period:
            raise ValueError("fast_period must be positive and smaller than slow_period")
        if stop_loss_pct <= 0 or take_profit_pct <= 0:
            raise ValueError("stop_loss_pct and take_profit_pct must be positive")
        self.account_id = account_id
        self.bot_id = bot_id
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.run_id = run_id
        self.timeframe = timeframe
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def on_candles(self, context: dict, candles: list[Candle]) -> list[Signal]:
        confirmed = self._confirmed(candles)
        if len(confirmed) < self.slow_period + 1:
            return []
        closes = [candle.close for candle in confirmed]
        previous_fast = self._sma(closes[-self.fast_period - 1 : -1])
        previous_slow = self._sma(closes[-self.slow_period - 1 : -1])
        fast = self._sma(closes[-self.fast_period :])
        slow = self._sma(closes[-self.slow_period :])
        if previous_fast <= previous_slow and fast > slow:
            return [self._open_signal()]
        return []

    def _confirmed(self, candles: list[Candle]) -> list[Candle]:
        return sorted(
            [
                candle
                for candle in candles
                if candle.confirmed and candle.symbol == self.symbol and candle.timeframe == self.timeframe
            ],
            key=lambda candle: candle.timestamp,
        )

    def _open_signal(self) -> Signal:
        return Signal(
            account_id=self.account_id,
            bot_id=self.bot_id,
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            run_id=self.run_id,
            action="open",
            direction="long",
            confidence=0.6,
            timeframe=self.timeframe,
            reason="fast SMA crossed above slow SMA",
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
        )

    def _sma(self, values: list[Decimal]) -> Decimal:
        return sum(values, start=Decimal("0")) / Decimal(len(values))
