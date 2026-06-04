from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from app.run_log import RuntimeEventLogger
from exchanges.okx.gateway import OKXGateway
from exchanges.okx.websocket import WebSocketConnector
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


@dataclass(frozen=True)
class LiveBotLoopResult:
    sync: LiveSyncResult
    gate: TradingGateResult | None


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
        gate = self._evaluate_gate() if self.config.evaluate_gate else None
        self._record(sync, gate)
        return LiveBotLoopResult(sync=sync, gate=gate)

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

    def _record(self, sync: LiveSyncResult, gate: TradingGateResult | None) -> None:
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
                "gate_status": gate.status if gate is not None else "skipped",
                "gate_reason": gate.reason if gate is not None else "skipped",
            },
        )
