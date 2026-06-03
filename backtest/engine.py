from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from core.models import BacktestMetrics, BacktestResult, BacktestTrade, Candle, EquityPoint, OrderIntent, Signal
from execution.order_factory import OrderFactory
from risk.manager import PortfolioRiskManager
from strategies.base import BaseStrategy
from strategies.runner import StrategyRunner


class BacktestEngine:
    def __init__(
        self,
        *,
        initial_equity: Decimal,
        fee_rate: Decimal = Decimal("0.0005"),
        slippage_rate: Decimal = Decimal("0.0002"),
        default_size: Decimal = Decimal("0.1"),
        tick_size: Decimal = Decimal("0.1"),
        lot_size: Decimal = Decimal("0.01"),
        min_size: Decimal = Decimal("0.01"),
    ) -> None:
        self.initial_equity = initial_equity
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.default_size = default_size
        self.tick_size = tick_size
        self.lot_size = lot_size
        self.min_size = min_size

    def run(self, strategy: BaseStrategy, candles: list[Candle]) -> BacktestResult:
        risk = PortfolioRiskManager()
        order_factory = OrderFactory()
        trades: list[BacktestTrade] = []
        runner = StrategyRunner(strategy)
        equity = self.initial_equity
        equity_curve: list[EquityPoint] = []
        open_trade: BacktestTrade | None = None
        pending_entry: tuple[OrderIntent, Signal] | None = None
        for idx in range(1, len(candles) + 1):
            window = candles[:idx]
            latest = window[-1]
            if pending_entry is not None and open_trade is None:
                order, signal = pending_entry
                entry_price = latest.open * (Decimal("1") + self.slippage_rate)
                entry_fee = entry_price * order.size * self.fee_rate
                open_trade = BacktestTrade(
                    symbol=order.symbol,
                    side=order.side,
                    entry_price=self._money(entry_price),
                    size=order.size,
                    fee=self._money(entry_fee),
                    opened_at=latest.timestamp,
                    stop_loss_price=self._exit_price(entry_price, signal.stop_loss_pct, "stop_loss"),
                    take_profit_price=self._exit_price(entry_price, signal.take_profit_pct, "take_profit"),
                )
                trades.append(open_trade)
                equity -= open_trade.fee
                pending_entry = None
            if open_trade is not None:
                close_event = self._maybe_close_trade(open_trade, latest)
                if close_event is not None:
                    exit_price, exit_reason = close_event
                    close_fee = exit_price * open_trade.size * self.fee_rate
                    pnl = (exit_price - open_trade.entry_price) * open_trade.size
                    open_trade.exit_price = self._money(exit_price)
                    open_trade.exit_reason = exit_reason
                    open_trade.closed_at = latest.timestamp
                    open_trade.fee += self._money(close_fee)
                    open_trade.pnl = self._money(pnl - open_trade.fee)
                    equity += open_trade.pnl
                    open_trade = None
            equity_curve.append(EquityPoint(timestamp=latest.timestamp, equity=self._money(equity)))
            signals = runner.run_on_candles(window)
            if not signals or open_trade is not None or pending_entry is not None:
                continue
            signal = signals[-1]
            decision = risk.evaluate(
                signal,
                equity=equity,
                open_positions=1 if open_trade else 0,
                entry_price=latest.close,
            )
            if not decision.approved:
                continue
            size = min(self.default_size, decision.adjusted_size)
            order = order_factory.from_signal(
                signal,
                size=size,
                price=None,
                tick_size=self.tick_size,
                lot_size=self.lot_size,
                min_size=self.min_size,
            )
            pending_entry = (order, signal)
        if open_trade is not None and candles:
            latest = candles[-1]
            close_fee = latest.close * open_trade.size * self.fee_rate
            pnl = (latest.close - open_trade.entry_price) * open_trade.size
            open_trade.exit_price = self._money(latest.close)
            open_trade.exit_reason = "end_of_data"
            open_trade.closed_at = latest.timestamp
            open_trade.fee += self._money(close_fee)
            open_trade.pnl = self._money(pnl - open_trade.fee)
            equity += open_trade.pnl
            if equity_curve:
                equity_curve[-1] = EquityPoint(timestamp=latest.timestamp, equity=self._money(equity))
        total_fees = sum((trade.fee for trade in trades), start=Decimal("0"))
        closed_trades = [trade for trade in trades if trade.closed_at is not None]
        winning = [trade for trade in closed_trades if trade.pnl > 0]
        final_equity = self._money(equity)
        trade_metrics = self._trade_metrics(closed_trades)
        metrics = BacktestMetrics(
            total_trades=len(closed_trades),
            win_rate=len(winning) / len(closed_trades) if closed_trades else 0.0,
            max_drawdown=self._max_drawdown(equity_curve),
            total_fees=self._money(total_fees),
            **trade_metrics,
        )
        return BacktestResult(
            initial_equity=self.initial_equity,
            final_equity=final_equity,
            trades=trades,
            metrics=metrics,
            equity_curve=equity_curve,
        )

    def _maybe_close_trade(self, trade: BacktestTrade, candle: Candle) -> tuple[Decimal, str] | None:
        if trade.side == "buy":
            if trade.stop_loss_price is not None and candle.low <= trade.stop_loss_price:
                return trade.stop_loss_price, "stop_loss"
            if trade.take_profit_price is not None and candle.high >= trade.take_profit_price:
                return trade.take_profit_price, "take_profit"
        return None

    def _exit_price(
        self,
        entry_price: Decimal,
        pct: float | None,
        kind: str,
    ) -> Decimal | None:
        if pct is None:
            return None
        pct_decimal = Decimal(str(pct))
        if kind == "stop_loss":
            return self._money(entry_price * (Decimal("1") - pct_decimal))
        return self._money(entry_price * (Decimal("1") + pct_decimal))

    def _max_drawdown(self, equity_curve: list[EquityPoint]) -> Decimal:
        if not equity_curve:
            return Decimal("0")
        peak = equity_curve[0].equity
        max_drawdown = Decimal("0")
        for point in equity_curve:
            if point.equity > peak:
                peak = point.equity
            if peak > 0:
                drawdown = (peak - point.equity) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
        return max_drawdown.quantize(Decimal("0.000001")).normalize()

    def _trade_metrics(self, trades: list[BacktestTrade]) -> dict[str, Decimal | int]:
        winning = [trade for trade in trades if trade.pnl > 0]
        losing = [trade for trade in trades if trade.pnl < 0]
        gross_profit = self._money(sum((trade.pnl for trade in winning), start=Decimal("0")))
        gross_loss = self._money(abs(sum((trade.pnl for trade in losing), start=Decimal("0"))))
        average_win = self._money(gross_profit / len(winning)) if winning else Decimal("0")
        average_loss = self._money(gross_loss / len(losing)) if losing else Decimal("0")
        profit_factor = self._ratio(gross_profit, gross_loss)
        payoff_ratio = self._ratio(average_win, average_loss)
        holding_seconds = [
            Decimal(str((trade.closed_at - trade.opened_at).total_seconds()))
            for trade in trades
            if trade.closed_at is not None
        ]
        average_holding_seconds = (
            sum(holding_seconds, start=Decimal("0")) / Decimal(len(holding_seconds)) if holding_seconds else Decimal("0")
        )
        return {
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "profit_factor": profit_factor,
            "average_win": average_win,
            "average_loss": average_loss,
            "payoff_ratio": payoff_ratio,
            "max_consecutive_losses": self._max_consecutive_losses(trades),
            "average_holding_seconds": average_holding_seconds.normalize(),
        }

    def _max_consecutive_losses(self, trades: list[BacktestTrade]) -> int:
        longest = 0
        current = 0
        for trade in trades:
            if trade.pnl < 0:
                current += 1
                longest = max(longest, current)
            else:
                current = 0
        return longest

    def _ratio(self, numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator == 0:
            return Decimal("0")
        return (numerator / denominator).quantize(Decimal("0.000001")).normalize()

    def _money(self, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
