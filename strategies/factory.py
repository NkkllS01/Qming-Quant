from __future__ import annotations

from strategies.base import BaseStrategy
from strategies.examples.ma_crossover import MovingAverageCrossoverStrategy
from strategies.examples.trend import MultiTimeframeTrendStrategy


def build_cli_strategy(strategy_name: str, *, symbol: str, timeframe: str, run_id: str) -> BaseStrategy:
    symbol_prefix = symbol.split("-")[0].lower()
    if strategy_name == "ma-crossover":
        return MovingAverageCrossoverStrategy(
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id=f"{symbol_prefix}_ma_crossover_{timeframe}",
            symbol=symbol,
            run_id=run_id,
            timeframe=timeframe,
        )
    return MultiTimeframeTrendStrategy(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id=f"{symbol_prefix}_trend_{timeframe}",
        symbol=symbol,
        run_id=run_id,
        timeframe=timeframe,
    )
