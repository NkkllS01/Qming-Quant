from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from core.models import Candle, OrderIntent, PaperJournalEvent, PaperRunResult, Signal
from execution.order_factory import OrderFactory
from paper.broker import PaperBroker
from risk.manager import PortfolioRiskManager
from risk.symbol_lease import SymbolLeaseManager
from strategies.base import BaseStrategy
from strategies.runner import StrategyRunner


@dataclass
class PaperExitPlan:
    order: OrderIntent
    stop_loss_price: Decimal | None
    take_profit_price: Decimal | None


class PaperTradingEngine:
    def __init__(
        self,
        *,
        initial_equity: Decimal,
        default_size: Decimal = Decimal("0.1"),
        max_risk_per_trade: Decimal = Decimal("0.005"),
        max_daily_loss: Decimal = Decimal("0.03"),
        max_total_drawdown_pause: Decimal = Decimal("0.08"),
        max_open_positions: int = 2,
        current_daily_loss: Decimal = Decimal("0"),
        current_drawdown: Decimal = Decimal("0"),
        tick_size: Decimal = Decimal("0.1"),
        lot_size: Decimal = Decimal("0.01"),
        min_size: Decimal = Decimal("0.01"),
    ) -> None:
        self.initial_equity = initial_equity
        self.default_size = default_size
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_total_drawdown_pause = max_total_drawdown_pause
        self.max_open_positions = max_open_positions
        self.current_daily_loss = current_daily_loss
        self.current_drawdown = current_drawdown
        self.tick_size = tick_size
        self.lot_size = lot_size
        self.min_size = min_size

    def run(self, strategy: BaseStrategy, candles: list[Candle]) -> PaperRunResult:
        broker = PaperBroker(initial_equity=self.initial_equity)
        runner = StrategyRunner(strategy)
        risk = PortfolioRiskManager(
            max_risk_per_trade=self.max_risk_per_trade,
            max_daily_loss=self.max_daily_loss,
            max_total_drawdown_pause=self.max_total_drawdown_pause,
            max_open_positions=self.max_open_positions,
        )
        leases = SymbolLeaseManager()
        order_factory = OrderFactory()
        journal: list[PaperJournalEvent] = []
        signals_count = 0
        approved_count = 0
        rejected_count = 0
        pending_order: tuple[OrderIntent, Signal] | None = None
        exit_plans: dict[str, PaperExitPlan] = {}

        for idx in range(1, len(candles) + 1):
            window = candles[:idx]
            latest = window[-1]
            if pending_order is not None:
                order, signal = pending_order
                fill = broker.execute(order, market_price=latest.open)
                exit_plans[order.symbol] = PaperExitPlan(
                    order=order,
                    stop_loss_price=self._exit_price(latest.open, signal.stop_loss_pct, "stop_loss"),
                    take_profit_price=self._exit_price(latest.open, signal.take_profit_pct, "take_profit"),
                )
                journal.append(
                    PaperJournalEvent(
                        event_type="fill",
                        symbol=fill.symbol,
                        strategy_id=fill.strategy_id,
                        message=f"{fill.side} {fill.size} @ {fill.price}",
                    )
                )
                pending_order = None
            self._close_triggered_positions(broker, latest, exit_plans, journal)
            signals = runner.run_on_candles(window)
            for signal in signals:
                signals_count += 1
                if signal.action == "open" and signal.symbol in broker.positions:
                    continue
                decision = risk.evaluate(
                    signal,
                    equity=broker.equity,
                    open_positions=len(broker.positions),
                    entry_price=latest.close,
                    current_daily_loss=self.current_daily_loss,
                    current_drawdown=self.current_drawdown,
                    open_symbols=set(broker.positions),
                )
                if not decision.approved:
                    rejected_count += 1
                    journal.append(
                        PaperJournalEvent(
                            event_type="risk_rejected",
                            symbol=signal.symbol,
                            strategy_id=signal.strategy_id,
                            message=decision.reason,
                        )
                    )
                    continue
                if signal.action == "open" and not leases.can_open(signal.symbol, signal.strategy_id):
                    rejected_count += 1
                    journal.append(
                        PaperJournalEvent(
                            event_type="lease_rejected",
                            symbol=signal.symbol,
                            strategy_id=signal.strategy_id,
                            message="symbol leased by another strategy",
                        )
                    )
                    continue
                if signal.action == "open":
                    leases.acquire(signal.symbol, signal.strategy_id)
                approved_count += 1
                order = order_factory.from_signal(
                    signal,
                    size=min(self.default_size, decision.adjusted_size),
                    price=None,
                    tick_size=self.tick_size,
                    lot_size=self.lot_size,
                    min_size=self.min_size,
                )
                pending_order = (order, signal)

        return PaperRunResult(
            initial_equity=self.initial_equity,
            final_equity=broker.equity,
            signals_count=signals_count,
            approved_count=approved_count,
            rejected_count=rejected_count,
            fills_count=len(broker.fills),
            positions_count=len(broker.positions),
            journal=journal,
            fills=broker.fills,
            positions=list(broker.positions.values()),
        )

    def _close_triggered_positions(
        self,
        broker: PaperBroker,
        candle: Candle,
        exit_plans: dict[str, PaperExitPlan],
        journal: list[PaperJournalEvent],
    ) -> None:
        for symbol, plan in list(exit_plans.items()):
            if symbol not in broker.positions:
                exit_plans.pop(symbol, None)
                continue
            close_event = self._maybe_close_long(plan, candle)
            if close_event is None:
                continue
            exit_price, exit_reason = close_event
            close_order = OrderIntent(
                account_id=plan.order.account_id,
                bot_id=plan.order.bot_id,
                strategy_id=plan.order.strategy_id,
                symbol=plan.order.symbol,
                run_id=plan.order.run_id,
                side="sell" if plan.order.side == "buy" else "buy",
                position_action="close",
                order_type="market",
                size=plan.order.size,
                price=None,
                reduce_only=True,
                client_order_id=f"{plan.order.client_order_id}-{exit_reason}",
            )
            fill = broker.execute(close_order, market_price=exit_price)
            journal.append(
                PaperJournalEvent(
                    event_type="fill",
                    symbol=fill.symbol,
                    strategy_id=fill.strategy_id,
                    message=f"{fill.side} {fill.size} @ {fill.price}",
                )
            )
            journal.append(
                PaperJournalEvent(
                    event_type=f"exit_{exit_reason}",
                    symbol=fill.symbol,
                    strategy_id=fill.strategy_id,
                    message=f"{exit_reason} @ {fill.price}",
                )
            )
            exit_plans.pop(symbol, None)

    def _maybe_close_long(self, plan: PaperExitPlan, candle: Candle) -> tuple[Decimal, str] | None:
        if plan.order.side != "buy":
            return None
        if plan.stop_loss_price is not None and candle.low <= plan.stop_loss_price:
            return plan.stop_loss_price, "stop_loss"
        if plan.take_profit_price is not None and candle.high >= plan.take_profit_price:
            return plan.take_profit_price, "take_profit"
        return None

    def _exit_price(self, entry_price: Decimal, pct: float | None, kind: str) -> Decimal | None:
        if pct is None:
            return None
        pct_decimal = Decimal(str(pct))
        if kind == "stop_loss":
            return self._money(entry_price * (Decimal("1") - pct_decimal))
        return self._money(entry_price * (Decimal("1") + pct_decimal))

    def _money(self, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
