from __future__ import annotations

from decimal import Decimal

from core.models import Candle, Signal
from strategies.base import BaseStrategy


class AtrChannelBreakoutStrategy(BaseStrategy):
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
        atr_period: int = 14,
        atr_multiplier: float = 2,
        reward_risk: float = 2,
        min_atr_pct: float = 0.001,
        max_atr_pct: float = 0.08,
    ) -> None:
        atr_multiplier_decimal = Decimal(str(atr_multiplier))
        reward_risk_decimal = Decimal(str(reward_risk))
        min_atr_pct_decimal = Decimal(str(min_atr_pct))
        max_atr_pct_decimal = Decimal(str(max_atr_pct))

        if lookback <= 0:
            raise ValueError("lookback must be positive")
        if atr_period <= 0:
            raise ValueError("atr_period must be positive")
        if atr_multiplier_decimal <= 0:
            raise ValueError("atr_multiplier must be positive")
        if reward_risk_decimal <= 0:
            raise ValueError("reward_risk must be positive")
        if min_atr_pct_decimal <= 0:
            raise ValueError("min_atr_pct must be positive")
        if max_atr_pct_decimal <= 0:
            raise ValueError("max_atr_pct must be positive")
        if min_atr_pct_decimal > max_atr_pct_decimal:
            raise ValueError("min_atr_pct must be less than or equal to max_atr_pct")

        self.account_id = account_id
        self.bot_id = bot_id
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.run_id = run_id
        self.timeframe = timeframe
        self.lookback = lookback
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier_decimal
        self.reward_risk = reward_risk_decimal
        self.min_atr_pct = min_atr_pct_decimal
        self.max_atr_pct = max_atr_pct_decimal

    def on_candles(self, context: dict, candles: list[Candle]) -> list[Signal]:
        confirmed = sorted(
            [
                candle
                for candle in candles
                if candle.confirmed and candle.symbol == self.symbol and candle.timeframe == self.timeframe
            ],
            key=lambda candle: candle.timestamp,
        )
        required_count = self.lookback + self.atr_period + 1
        if len(confirmed) < required_count:
            return []

        working_set = confirmed[-required_count:]
        latest = working_set[-1]
        channel = working_set[-self.lookback - 1 : -1]
        prior_channel_high = max(candle.high for candle in channel)
        if latest.close <= prior_channel_high:
            return []

        atr_candles = working_set[-self.atr_period - 2 : -1]
        atr = self._average_true_range(atr_candles)
        atr_pct = atr / latest.close
        if atr_pct < self.min_atr_pct or atr_pct > self.max_atr_pct:
            return []

        stop_loss_pct = (self.atr_multiplier * atr) / latest.close
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
                confidence=0.75,
                timeframe=self.timeframe,
                reason="close above prior Donchian channel high",
                stop_loss_pct=float(stop_loss_pct),
                take_profit_pct=float(take_profit_pct),
            )
        ]

    def _average_true_range(self, candles: list[Candle]) -> Decimal:
        true_ranges: list[Decimal] = []
        previous_close = candles[0].close
        for candle in candles[1:]:
            high_low = candle.high - candle.low
            true_ranges.append(
                max(high_low, abs(candle.high - previous_close), abs(candle.low - previous_close))
            )
            previous_close = candle.close
        return sum(true_ranges) / Decimal(len(true_ranges))
