from __future__ import annotations

from app.live_services import build_market_data_guard
from app.services import AppServices


def evaluate_prelive_readiness(services: AppServices, *, account_id: str, symbols: list[str]) -> dict:
    issues: list[str] = []
    pause_state = services.safety_repository.get_pause(account_id=account_id) if services.safety_repository is not None else None
    manual_paused = pause_state.paused if pause_state is not None else False
    if pause_state is None:
        issues.append("missing_safety_repository")
    elif pause_state.paused:
        issues.append("manual_pause")

    runtime_log = "configured" if services.runtime_logger is not None else "disabled"
    if services.runtime_logger is None:
        issues.append("runtime_log_disabled")

    missing_instruments = missing_instruments_for_symbols(services, symbols)
    instruments = "ok" if not missing_instruments else f"missing:{'|'.join(missing_instruments)}"
    if missing_instruments:
        issues.append("missing_instruments")

    market_data = build_market_data_guard(services, symbols=symbols)
    if market_data is None:
        mark_prices = "unavailable"
        issues.append("missing_mark_price_repository")
    else:
        market_result = market_data.evaluate()
        mark_prices = market_data_readiness_status(market_result)
        if not market_result.trading_allowed:
            issues.append(market_result.reason)

    balance_snapshot = balance_snapshot_status(services, account_id)
    if balance_snapshot != "available":
        issues.append(balance_snapshot)

    return {
        "status": "ready" if not issues else "blocked",
        "manual_paused": manual_paused,
        "runtime_log": runtime_log,
        "instruments": instruments,
        "mark_prices": mark_prices,
        "balance_snapshot": balance_snapshot,
        "issues": issues,
    }


def missing_instruments_for_symbols(services: AppServices, symbols: list[str]) -> list[str]:
    if services.instrument_repository is None:
        return list(symbols)
    return [symbol for symbol in symbols if services.instrument_repository.get(symbol) is None]


def balance_snapshot_status(services: AppServices, account_id: str) -> str:
    if services.live_state_repository is None:
        return "missing_live_state_repository"
    store = services.live_state_repository.load_snapshot(account_id=account_id)
    balance = store.balances.get("USDT")
    if balance is None:
        return "missing_balance_snapshot"
    if balance.equity <= 0:
        return "invalid_balance_snapshot"
    return "available"


def market_data_readiness_status(result) -> str:
    if result.trading_allowed:
        return result.reason
    parts = [result.reason]
    if result.missing_symbols:
        parts.append(f"missing={'|'.join(result.missing_symbols)}")
    if result.stale_symbols:
        parts.append(f"stale={'|'.join(result.stale_symbols)}")
    return ":".join(parts)
