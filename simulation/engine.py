from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from core.models import Candle, OrderIntent, Signal, SimulationJournalEvent, SimulationRunResult
from execution.order_factory import OrderFactory
from risk.manager import PortfolioRiskManager
from risk.symbol_lease import SymbolLeaseManager
from simulation.broker import SimulationBroker
from strategies.base import BaseStrategy
from strategies.runner import StrategyRunner


@dataclass
class SimulationExitPlan:
    order: OrderIntent
    stop_loss_price: Decimal | None
    take_profit_price: Decimal | None


class SimulationTradingEngine:
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
        fill_id_prefix: str = "sim",
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
        self.fill_id_prefix = fill_id_prefix

    def run(self, strategy: BaseStrategy, candles: list[Candle]) -> SimulationRunResult:
        broker = SimulationBroker(
            initial_equity=self.initial_equity,
            fill_id_prefix=self.fill_id_prefix,
        )
        runner = StrategyRunner(strategy)
        risk = PortfolioRiskManager(
            max_risk_per_trade=self.max_risk_per_trade,
            max_daily_loss=self.max_daily_loss,
            max_total_drawdown_pause=self.max_total_drawdown_pause,
            max_open_positions=self.max_open_positions,
        )
        leases = SymbolLeaseManager()
        order_factory = OrderFactory()
        journal: list[SimulationJournalEvent] = []
        signals_count = 0
        approved_count = 0
        rejected_count = 0
        pending_order: tuple[OrderIntent, Signal] | None = None
        exit_plans: dict[str, SimulationExitPlan] = {}

        for idx in range(1, len(candles) + 1):
            window = candles[:idx]
            latest = window[-1]
            if pending_order is not None:
                pending_order = self._fill_pending_order(
                    pending_order,
                    broker,
                    latest,
                    exit_plans,
                    journal,
                )
            self._close_triggered_positions(broker, latest, exit_plans, journal)
            for signal in runner.run_on_candles(window):
                signals_count += 1
                outcome = self._handle_signal(signal, broker, risk, leases, order_factory, latest)
                rejected_count += int(outcome.rejected)
                approved_count += int(outcome.order is not None)
                if outcome.event is not None:
                    journal.append(outcome.event)
                if outcome.order is not None:
                    pending_order = (outcome.order, signal)

        return SimulationRunResult(
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

    def _fill_pending_order(
        self,
        pending_order: tuple[OrderIntent, Signal],
        broker: SimulationBroker,
        latest: Candle,
        exit_plans: dict[str, SimulationExitPlan],
        journal: list[SimulationJournalEvent],
    ) -> None:
        order, signal = pending_order
        fill = broker.execute(order, market_price=latest.open)
        exit_plans[order.symbol] = SimulationExitPlan(
            order=order,
            stop_loss_price=self._exit_price(latest.open, signal.stop_loss_pct, "stop_loss"),
            take_profit_price=self._exit_price(latest.open, signal.take_profit_pct, "take_profit"),
        )
        journal.append(_journal_event("fill", fill.symbol, fill.strategy_id, f"{fill.side} {fill.size} @ {fill.price}"))
        return None

    def _handle_signal(
        self,
        signal: Signal,
        broker: SimulationBroker,
        risk: PortfolioRiskManager,
        leases: SymbolLeaseManager,
        order_factory: OrderFactory,
        latest: Candle,
    ) -> "_SignalOutcome":
        if signal.action == "open" and signal.symbol in broker.positions:
            return _SignalOutcome()
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
            return _SignalOutcome(
                rejected=True,
                event=_journal_event("risk_rejected", signal.symbol, signal.strategy_id, decision.reason),
            )
        if signal.action == "open" and not leases.can_open(signal.symbol, signal.strategy_id):
            return _SignalOutcome(
                rejected=True,
                event=_journal_event(
                    "lease_rejected",
                    signal.symbol,
                    signal.strategy_id,
                    "symbol leased by another strategy",
                ),
            )
        if signal.action == "open":
            leases.acquire(signal.symbol, signal.strategy_id)
        return _SignalOutcome(
            order=order_factory.from_signal(
                signal,
                size=min(self.default_size, decision.adjusted_size),
                price=None,
                tick_size=self.tick_size,
                lot_size=self.lot_size,
                min_size=self.min_size,
            )
        )

    def _close_triggered_positions(
        self,
        broker: SimulationBroker,
        candle: Candle,
        exit_plans: dict[str, SimulationExitPlan],
        journal: list[SimulationJournalEvent],
    ) -> None:
        for symbol, plan in list(exit_plans.items()):
            if symbol not in broker.positions:
                exit_plans.pop(symbol, None)
                continue
            close_event = self._maybe_close_long(plan, candle)
            if close_event is None:
                continue
            self._close_position_with_plan(broker, plan, close_event, journal)
            exit_plans.pop(symbol, None)

    def _close_position_with_plan(
        self,
        broker: SimulationBroker,
        plan: SimulationExitPlan,
        close_event: tuple[Decimal, str],
        journal: list[SimulationJournalEvent],
    ) -> None:
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
        journal.append(_journal_event("fill", fill.symbol, fill.strategy_id, f"{fill.side} {fill.size} @ {fill.price}"))
        journal.append(_journal_event(f"exit_{exit_reason}", fill.symbol, fill.strategy_id, f"{exit_reason} @ {fill.price}"))

    def _maybe_close_long(self, plan: SimulationExitPlan, candle: Candle) -> tuple[Decimal, str] | None:
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


@dataclass
class _SignalOutcome:
    order: OrderIntent | None = None
    rejected: bool = False
    event: SimulationJournalEvent | None = None


def _journal_event(
    event_type: str,
    symbol: str,
    strategy_id: str,
    message: str,
) -> SimulationJournalEvent:
    return SimulationJournalEvent(
        event_type=event_type,
        symbol=symbol,
        strategy_id=strategy_id,
        message=message,
    )
