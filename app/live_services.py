from __future__ import annotations

from app.services import AppServices
from live.market_data_guard import LiveMarketDataGuard
from live.reconcile import LiveReconciliationService
from live.risk import LiveEquityRiskGuard
from live.trading_gate import TradingGateService


def build_market_data_guard(services: AppServices, *, symbols: list[str]) -> LiveMarketDataGuard | None:
    if services.mark_price_repository is None:
        return None
    return LiveMarketDataGuard(
        mark_price_repository=services.mark_price_repository,
        symbols=symbols,
        max_mark_price_age_seconds=services.max_mark_price_age_seconds,
    )


def build_trading_gate(services: AppServices, *, account_id: str, symbols: list[str]) -> TradingGateService:
    if services.live_state_repository is None:
        raise RuntimeError("Live state repository is not configured")
    if services.safety_repository is None:
        raise RuntimeError("Safety repository is not configured")
    reconciliation = LiveReconciliationService(
        gateway=services.gateway,
        repository=services.live_state_repository,
        account_id=account_id,
    )
    equity_risk_guard = LiveEquityRiskGuard(
        live_state_repository=services.live_state_repository,
        safety_repository=services.safety_repository,
        account_id=account_id,
        max_daily_loss=services.max_daily_loss,
        max_total_drawdown=services.max_total_drawdown_pause,
    )
    return TradingGateService(
        reconciliation=reconciliation,
        safety_repository=services.safety_repository,
        account_id=account_id,
        equity_risk_guard=equity_risk_guard,
        market_data_guard=build_market_data_guard(services, symbols=symbols),
    )


def evaluate_cli_trading_gate(services: AppServices, *, account_id: str, symbols: list[str]):
    return build_trading_gate(services, account_id=account_id, symbols=symbols).evaluate()
