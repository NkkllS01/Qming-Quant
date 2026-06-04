from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from app.live_services import build_trading_gate
from app.run_log import RuntimeEventLogger
from app.services import AppServices
from core.models import OrderIntent, RiskDecision, Signal
from execution.order_factory import OrderFactory
from live.execution import LiveOrderCheckResult, LiveOrderExecutionService
from risk.manager import PortfolioRiskManager
from storage.live_intent_repository import LiveIntentRepository, live_intent_entry
from storage.live_repository import LiveStateRepository
from storage.repositories import CandleRepository, FundingRateRepository, InstrumentRepository, MarkPriceRepository
from storage.safety_repository import SafetyRepository
from strategies.factory import build_cli_strategy
from strategies.runner import StrategyRunner


@dataclass(frozen=True)
class LiveStrategyDryRunConfig:
    account_id: str
    symbol: str
    timeframe: str
    strategy: str = "trend"
    run_id: str | None = None
    min_candles: int = 30


@dataclass(frozen=True)
class LiveStrategyDryRunDecision:
    status: str
    signal: Signal
    intent: OrderIntent
    risk_reason: str
    policy_reason: str
    gate_reason: str


@dataclass(frozen=True)
class LiveStrategyDryRunResult:
    run_id: str
    signals_count: int
    intents_count: int
    allowed_count: int
    rejected_count: int
    decisions: list[LiveStrategyDryRunDecision]


class LiveStrategyDryRunService:
    def __init__(
        self,
        *,
        gateway: object,
        candle_repository: CandleRepository,
        instrument_repository: InstrumentRepository,
        mark_price_repository: MarkPriceRepository,
        live_state_repository: LiveStateRepository,
        safety_repository: SafetyRepository,
        intent_repository: LiveIntentRepository,
        funding_rate_repository: FundingRateRepository | None = None,
        runtime_logger: RuntimeEventLogger | None = None,
        max_risk_per_trade: Decimal = Decimal("0.005"),
        max_daily_loss: Decimal = Decimal("0.03"),
        max_total_drawdown: Decimal = Decimal("0.08"),
        max_open_positions: int = 2,
        max_mark_price_age_seconds: int = 120,
    ) -> None:
        self.gateway = gateway
        self.candle_repository = candle_repository
        self.instrument_repository = instrument_repository
        self.mark_price_repository = mark_price_repository
        self.live_state_repository = live_state_repository
        self.safety_repository = safety_repository
        self.intent_repository = intent_repository
        self.funding_rate_repository = funding_rate_repository
        self.runtime_logger = runtime_logger
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_total_drawdown = max_total_drawdown
        self.max_open_positions = max_open_positions
        self.max_mark_price_age_seconds = max_mark_price_age_seconds

    @classmethod
    def from_services(cls, services: AppServices) -> "LiveStrategyDryRunService":
        if services.instrument_repository is None:
            raise RuntimeError("Instrument repository is not configured")
        if services.mark_price_repository is None:
            raise RuntimeError("Mark price repository is not configured")
        if services.live_state_repository is None:
            raise RuntimeError("Live state repository is not configured")
        if services.safety_repository is None:
            raise RuntimeError("Safety repository is not configured")
        if services.live_intent_repository is None:
            raise RuntimeError("Live intent repository is not configured")
        return cls(
            gateway=services.gateway,
            candle_repository=services.candle_repository,
            instrument_repository=services.instrument_repository,
            mark_price_repository=services.mark_price_repository,
            live_state_repository=services.live_state_repository,
            safety_repository=services.safety_repository,
            intent_repository=services.live_intent_repository,
            funding_rate_repository=services.funding_rate_repository,
            runtime_logger=services.runtime_logger,
            max_risk_per_trade=services.max_risk_per_trade,
            max_daily_loss=services.max_daily_loss,
            max_total_drawdown=services.max_total_drawdown_pause,
            max_open_positions=services.max_open_positions,
            max_mark_price_age_seconds=services.max_mark_price_age_seconds,
        )

    def run(self, config: LiveStrategyDryRunConfig) -> LiveStrategyDryRunResult:
        run_id = config.run_id or f"live-dry-{uuid4().hex[:10]}"
        candles = self.candle_repository.list_candles(config.symbol, config.timeframe)
        if len(candles) < config.min_candles:
            result = LiveStrategyDryRunResult(run_id, 0, 0, 0, 0, [])
            self._record_summary(config, result, reason="insufficient_candles")
            return result
        strategy = build_cli_strategy(config.strategy, symbol=config.symbol, timeframe=config.timeframe, run_id=run_id)
        context = self._strategy_context(config)
        signals = StrategyRunner(strategy).run_on_candles(candles, context=context)
        decisions = [self._evaluate_signal(config, run_id, index, signal) for index, signal in enumerate(signals)]
        result = LiveStrategyDryRunResult(
            run_id=run_id,
            signals_count=len(signals),
            intents_count=len(decisions),
            allowed_count=sum(1 for decision in decisions if decision.status == "allowed"),
            rejected_count=sum(1 for decision in decisions if decision.status != "allowed"),
            decisions=decisions,
        )
        self._record_summary(config, result, reason="completed")
        return result

    def _strategy_context(self, config: LiveStrategyDryRunConfig) -> dict:
        mark_price = self.mark_price_repository.get(config.symbol)
        context = {"mark_price": mark_price}
        if self.funding_rate_repository is not None:
            context["funding_rates"] = self.funding_rate_repository.list_rates(config.symbol)
        return context

    def _evaluate_signal(
        self,
        config: LiveStrategyDryRunConfig,
        run_id: str,
        index: int,
        signal: Signal,
    ) -> LiveStrategyDryRunDecision:
        instrument = self.instrument_repository.get(config.symbol)
        if instrument is None:
            raise RuntimeError(f"missing instrument spec for {config.symbol}")
        mark_price = self.mark_price_repository.get(config.symbol)
        if mark_price is None:
            raise RuntimeError(f"missing mark price for {config.symbol}")
        store = self.live_state_repository.load_snapshot(account_id=config.account_id)
        balance = store.balances.get("USDT")
        if balance is None:
            raise RuntimeError("missing USDT balance snapshot")
        open_symbols = {position.symbol for position in store.positions.values() if position.size != 0}
        risk = PortfolioRiskManager(
            max_risk_per_trade=self.max_risk_per_trade,
            max_daily_loss=self.max_daily_loss,
            max_total_drawdown_pause=self.max_total_drawdown,
            max_open_positions=self.max_open_positions,
        ).evaluate(
            signal,
            equity=balance.equity,
            open_positions=len(open_symbols),
            entry_price=mark_price.mark_price,
            open_symbols=open_symbols,
        )
        intent = self._intent_from_signal(signal, risk, mark_price.mark_price, instrument, index)
        check = None if not risk.approved else self._check_order(config, intent)
        decision = _decision_from_results(signal, intent, risk, check)
        self.intent_repository.append(
            live_intent_entry(
                run_id=run_id,
                event_index=index,
                account_id=intent.account_id,
                bot_id=intent.bot_id,
                strategy_id=intent.strategy_id,
                symbol=intent.symbol,
                timeframe=signal.timeframe,
                signal_action=signal.action,
                signal_direction=signal.direction,
                signal_reason=signal.reason,
                client_order_id=intent.client_order_id,
                side=intent.side,
                position_action=intent.position_action,
                order_type=intent.order_type,
                size=intent.size,
                price=intent.price,
                status=decision.status,
                risk_reason=decision.risk_reason,
                policy_reason=decision.policy_reason,
                gate_reason=decision.gate_reason,
            )
        )
        return decision

    def _intent_from_signal(self, signal: Signal, risk: RiskDecision, entry_price: Decimal, instrument, index: int) -> OrderIntent:
        size = risk.adjusted_size if risk.adjusted_size > 0 else instrument.min_size
        intent = OrderFactory().from_signal(
            signal,
            size=size,
            price=None,
            tick_size=instrument.tick_size,
            lot_size=instrument.lot_size,
            min_size=instrument.min_size,
        )
        return intent.model_copy(update={"client_order_id": f"dry{uuid4().hex[:16]}{index:02d}"})

    def _check_order(self, config: LiveStrategyDryRunConfig, intent: OrderIntent) -> LiveOrderCheckResult:
        services = AppServices(
            gateway=self.gateway,
            candle_repository=self.candle_repository,
            instrument_repository=self.instrument_repository,
            mark_price_repository=self.mark_price_repository,
            live_state_repository=self.live_state_repository,
            safety_repository=self.safety_repository,
            max_daily_loss=self.max_daily_loss,
            max_total_drawdown_pause=self.max_total_drawdown,
            max_mark_price_age_seconds=self.max_mark_price_age_seconds,
        )
        gate = build_trading_gate(services, account_id=config.account_id, symbols=[config.symbol])
        return LiveOrderExecutionService(
            gateway=self.gateway,
            trading_gate=gate,
            live_state_repository=self.live_state_repository,
            instrument_repository=self.instrument_repository,
        ).check_order(intent)

    def _record_summary(self, config: LiveStrategyDryRunConfig, result: LiveStrategyDryRunResult, *, reason: str) -> None:
        if self.runtime_logger is None:
            return
        self.runtime_logger.record(
            command="live-strategy-dry-run",
            outcome=reason,
            details={
                "account_id": config.account_id,
                "symbol": config.symbol,
                "timeframe": config.timeframe,
                "strategy": config.strategy,
                "run_id": result.run_id,
                "signals": result.signals_count,
                "intents": result.intents_count,
                "allowed": result.allowed_count,
                "rejected": result.rejected_count,
            },
        )


def _decision_from_results(
    signal: Signal,
    intent: OrderIntent,
    risk: RiskDecision,
    check: LiveOrderCheckResult | None,
) -> LiveStrategyDryRunDecision:
    if not risk.approved:
        return LiveStrategyDryRunDecision(
            status="risk_rejected",
            signal=signal,
            intent=intent,
            risk_reason=risk.reason,
            policy_reason="not_checked",
            gate_reason="not_checked",
        )
    if check is None:
        raise RuntimeError("risk-approved dry-run decision requires an order check")
    gate_reason = check.trading_gate.reason if check.trading_gate is not None else "not_checked"
    return LiveStrategyDryRunDecision(
        status=check.status,
        signal=signal,
        intent=intent,
        risk_reason=risk.reason,
        policy_reason=check.policy.reason,
        gate_reason=gate_reason,
    )
