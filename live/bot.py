from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal

from app.run_log import RuntimeEventLogger
from exchanges.okx.gateway import OKXGateway
from exchanges.okx.websocket import WebSocketConnector
from live.fill_sync import FillSyncResult, LiveFillSyncService
from live.market_data_guard import LiveMarketDataGuard
from live.reconcile import LiveReconciliationService
from live.risk import LiveEquityRiskGuard
from live.sync import LiveSyncResult, LiveSyncService
from live.trading_gate import TradingGateResult, TradingGateService
from storage.live_repository import LiveStateRepository
from storage.repositories import MarkPriceRepository
from storage.safety_repository import SafetyRepository


@dataclass(frozen=True)
class LiveBotConfig:
    account_id: str
    symbols: list[str]
    include_fills_channel: bool = False
    max_messages_per_connection: int = 1
    evaluate_gate: bool = True
    interval_seconds: float = 5
    max_iterations: int | None = None
    fill_backfill_limit: int = 100


@dataclass(frozen=True)
class LiveBotLoopResult:
    sync: LiveSyncResult
    fill_backfill: FillSyncResult
    gate: TradingGateResult | None


@dataclass(frozen=True)
class LiveBotRunSummary:
    iterations: int
    completed_iterations: int
    failed_iterations: int
    last_result: LiveBotLoopResult | None
    last_error: str | None = None


class LiveBotLoop:
    def __init__(
        self,
        *,
        config: LiveBotConfig,
        gateway: OKXGateway,
        connector: WebSocketConnector,
        live_state_repository: LiveStateRepository,
        safety_repository: SafetyRepository,
        mark_price_repository: MarkPriceRepository | None = None,
        runtime_logger: RuntimeEventLogger | None = None,
        max_daily_loss=Decimal("0.03"),
        max_total_drawdown=Decimal("0.08"),
        max_mark_price_age_seconds: int = 120,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.connector = connector
        self.live_state_repository = live_state_repository
        self.safety_repository = safety_repository
        self.mark_price_repository = mark_price_repository
        self.runtime_logger = runtime_logger
        self.max_daily_loss = max_daily_loss
        self.max_total_drawdown = max_total_drawdown
        self.max_mark_price_age_seconds = max_mark_price_age_seconds

    def run_once(self) -> LiveBotLoopResult:
        sync = asyncio.run(
            LiveSyncService(
                gateway=self.gateway,
                connector=self.connector,
                account_id=self.config.account_id,
                symbols=self.config.symbols,
                repository=self.live_state_repository,
                include_fills_channel=self.config.include_fills_channel,
            ).run_once(max_messages_per_connection=self.config.max_messages_per_connection)
        )
        fill_backfill = self._backfill_fills()
        gate = self._evaluate_gate() if self.config.evaluate_gate else None
        self._record(sync, fill_backfill, gate)
        return LiveBotLoopResult(sync=sync, fill_backfill=fill_backfill, gate=gate)

    def run(self) -> LiveBotRunSummary:
        iterations = 0
        completed_iterations = 0
        failed_iterations = 0
        last_result = None
        last_error = None
        while self.config.max_iterations is None or iterations < self.config.max_iterations:
            iterations += 1
            try:
                last_result = self.run_once()
                completed_iterations += 1
                last_error = None
            except Exception as exc:
                failed_iterations += 1
                last_error = str(exc)
                self._record_iteration_failure(iterations, exc)
            if self.config.max_iterations is not None and iterations >= self.config.max_iterations:
                break
            if self.config.interval_seconds > 0:
                time.sleep(self.config.interval_seconds)
        summary = LiveBotRunSummary(
            iterations=iterations,
            completed_iterations=completed_iterations,
            failed_iterations=failed_iterations,
            last_result=last_result,
            last_error=last_error,
        )
        self._record_run_summary(summary)
        return summary

    def _backfill_fills(self) -> FillSyncResult:
        fetched_count = 0
        stored_count = 0
        matched_count = 0
        service = LiveFillSyncService(
            gateway=self.gateway,
            repository=self.live_state_repository,
            account_id=self.config.account_id,
        )
        for symbol in self.config.symbols:
            result = service.run(symbol=symbol, limit=self.config.fill_backfill_limit)
            fetched_count += result.fetched_count
            stored_count += result.stored_count
            matched_count += result.matched_count
        return FillSyncResult(
            fetched_count=fetched_count,
            stored_count=stored_count,
            matched_count=matched_count,
        )

    def _evaluate_gate(self) -> TradingGateResult:
        market_data_guard = None
        if self.mark_price_repository is not None:
            market_data_guard = LiveMarketDataGuard(
                mark_price_repository=self.mark_price_repository,
                symbols=self.config.symbols,
                max_mark_price_age_seconds=self.max_mark_price_age_seconds,
            )
        return TradingGateService(
            reconciliation=LiveReconciliationService(
                gateway=self.gateway,
                repository=self.live_state_repository,
                account_id=self.config.account_id,
            ),
            safety_repository=self.safety_repository,
            account_id=self.config.account_id,
            equity_risk_guard=LiveEquityRiskGuard(
                live_state_repository=self.live_state_repository,
                safety_repository=self.safety_repository,
                account_id=self.config.account_id,
                max_daily_loss=self.max_daily_loss,
                max_total_drawdown=self.max_total_drawdown,
            ),
            market_data_guard=market_data_guard,
        ).evaluate()

    def _record(self, sync: LiveSyncResult, fill_backfill: FillSyncResult, gate: TradingGateResult | None) -> None:
        if self.runtime_logger is None:
            return
        self.runtime_logger.record(
            command="live-bot-once",
            outcome=gate.status if gate is not None else "completed",
            details={
                "account_id": self.config.account_id,
                "symbols": self.config.symbols,
                "public_messages": sync.public_messages,
                "private_messages": sync.private_messages,
                "tickers": sync.tickers_count,
                "balances": sync.balances_count,
                "positions": sync.positions_count,
                "orders": sync.orders_count,
                "fills": sync.fills_count,
                "persisted": sync.persisted,
                "fill_backfill_fetched": fill_backfill.fetched_count,
                "fill_backfill_stored": fill_backfill.stored_count,
                "fill_backfill_matched": fill_backfill.matched_count,
                "gate_status": gate.status if gate is not None else "skipped",
                "gate_reason": gate.reason if gate is not None else "skipped",
            },
        )

    def _record_iteration_failure(self, iteration: int, exc: Exception) -> None:
        if self.runtime_logger is None:
            return
        self.runtime_logger.record(
            command="live-bot-run-iteration",
            outcome="failed",
            details={
                "account_id": self.config.account_id,
                "symbols": self.config.symbols,
                "iteration": iteration,
                "error": str(exc),
            },
        )

    def _record_run_summary(self, summary: LiveBotRunSummary) -> None:
        if self.runtime_logger is None:
            return
        self.runtime_logger.record(
            command="live-bot-run",
            outcome="completed" if summary.failed_iterations == 0 else "completed_with_errors",
            details={
                "account_id": self.config.account_id,
                "symbols": self.config.symbols,
                "iterations": summary.iterations,
                "completed_iterations": summary.completed_iterations,
                "failed_iterations": summary.failed_iterations,
                "last_error": summary.last_error,
            },
        )
