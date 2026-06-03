from __future__ import annotations

from decimal import Decimal

from core.models import Candle, Signal
from strategies.base import BaseStrategy


class MultiTimeframeTrendStrategy(BaseStrategy):
    def __init__(
        self,
        *,
        account_id: str,
        bot_id: str,
        strategy_id: str,
        symbol: str,
        run_id: str,
        timeframe: str = "15m",
        lookback: int = 20,
        higher_timeframe: str = "1h",
        fast_ema_period: int = 10,
        slow_ema_period: int = 20,
        atr_period: int = 14,
        atr_stop_multiplier: Decimal | int | str = Decimal("1.5"),
        reward_risk: Decimal | int | str = Decimal("2"),
    ) -> None:
        if fast_ema_period <= 0 or slow_ema_period <= 0 or fast_ema_period >= slow_ema_period:
            raise ValueError("fast_ema_period must be positive and smaller than slow_ema_period")
        if atr_period <= 0:
            raise ValueError("atr_period must be positive")
        if Decimal(str(atr_stop_multiplier)) <= 0 or Decimal(str(reward_risk)) <= 0:
            raise ValueError("atr_stop_multiplier and reward_risk must be positive")
        self.account_id = account_id
        self.bot_id = bot_id
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.run_id = run_id
        self.timeframe = timeframe
        self.lookback = lookback
        self.higher_timeframe = higher_timeframe
        self.fast_ema_period = fast_ema_period
        self.slow_ema_period = slow_ema_period
        self.atr_period = atr_period
        self.atr_stop_multiplier = Decimal(str(atr_stop_multiplier))
        self.reward_risk = Decimal(str(reward_risk))

    def on_candles(self, context: dict, candles: list[Candle]) -> list[Signal]:
        confirmed = self._confirmed(candles, self.timeframe)
        higher_candles = context.get("higher_timeframe_candles")
        higher_confirmed = (
            self._confirmed(higher_candles, self.higher_timeframe)
            if isinstance(higher_candles, list)
            else confirmed
        )
        min_entry_candles = max(self.slow_ema_period + 2, self.atr_period + 2, self.lookback + 1)
        if len(confirmed) < min_entry_candles or len(higher_confirmed) < self.slow_ema_period + 1:
            return []
        latest = confirmed[-1]
        fast_ema = self._ema([candle.close for candle in confirmed], self.fast_ema_period)
        slow_ema = self._ema([candle.close for candle in confirmed], self.slow_ema_period)
        previous_fast_ema = self._ema([candle.close for candle in confirmed[:-1]], self.fast_ema_period)
        previous_slow_ema = self._ema([candle.close for candle in confirmed[:-1]], self.slow_ema_period)
        higher_fast_ema = self._ema([candle.close for candle in higher_confirmed], self.fast_ema_period)
        higher_slow_ema = self._ema([candle.close for candle in higher_confirmed], self.slow_ema_period)
        atr = self._average_true_range(confirmed[-self.atr_period - 1 :])
        if (
            latest.close > fast_ema
            and fast_ema > slow_ema
            and fast_ema > previous_fast_ema
            and slow_ema >= previous_slow_ema
            and higher_fast_ema > higher_slow_ema
            and atr > 0
        ):
            stop_loss_pct = (atr * self.atr_stop_multiplier) / latest.close
            take_profit_pct = stop_loss_pct * self.reward_risk
            return [
                Signal(
                    account_id=self.account_id,
                    bot_id=self.bot_id,
                    strategy_id=self.strategy_id,
                    symbol=self.symbol,
                    run_id=self.run_id,
                    action="open",
                    direction="long",
                    confidence=0.7,
                    timeframe=self.timeframe,
                    reason="multi-timeframe EMA trend breakout",
                    stop_loss_pct=float(stop_loss_pct),
                    take_profit_pct=float(take_profit_pct),
                )
            ]
        return []

    def _confirmed(self, candles: list[Candle], timeframe: str) -> list[Candle]:
        return sorted(
            [
                candle
                for candle in candles
                if candle.confirmed and candle.symbol == self.symbol and candle.timeframe == timeframe
            ],
            key=lambda candle: candle.timestamp,
        )

    def _ema(self, values: list[Decimal], period: int) -> Decimal:
        if len(values) < period:
            return Decimal("0")
        alpha = Decimal("2") / Decimal(period + 1)
        ema = sum(values[:period], start=Decimal("0")) / Decimal(period)
        for value in values[period:]:
            ema = (value * alpha) + (ema * (Decimal("1") - alpha))
        return ema

    def _average_true_range(self, candles: list[Candle]) -> Decimal:
        if len(candles) < 2:
            return Decimal("0")
        true_ranges: list[Decimal] = []
        previous_close = candles[0].close
        for candle in candles[1:]:
            true_ranges.append(
                max(
                    candle.high - candle.low,
                    abs(candle.high - previous_close),
                    abs(candle.low - previous_close),
                )
            )
            previous_close = candle.close
        return sum(true_ranges, start=Decimal("0")) / Decimal(len(true_ranges))
