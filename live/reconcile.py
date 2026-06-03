from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from core.models import Order
from execution.reconciliation import Reconciliation, ReconciliationIssue
from storage.live_repository import LiveStateRepository

ACTIVE_LOCAL_ORDER_STATUSES = {
    "submitted",
    "pending",
    "live",
    "partially_filled",
    "cancel_requested",
    "unknown",
}


@dataclass(frozen=True)
class LiveReconcileResult:
    status: str
    positions_issues: list[ReconciliationIssue]
    missing_orders_on_exchange: set[str]
    missing_orders_locally: set[str]

    @property
    def is_clean(self) -> bool:
        return (
            not self.positions_issues
            and not self.missing_orders_on_exchange
            and not self.missing_orders_locally
        )


class LiveReconciliationService:
    def __init__(
        self,
        *,
        gateway: object,
        repository: LiveStateRepository,
        account_id: str,
    ) -> None:
        self.gateway = gateway
        self.repository = repository
        self.account_id = account_id
        self.reconciliation = Reconciliation()

    def run(self) -> LiveReconcileResult:
        local_store = self.repository.load_snapshot(account_id=self.account_id)
        exchange_positions = _normalize_okx_positions(self.gateway.positions())
        positions_report = self.reconciliation.compare_positions(
            list(local_store.positions.values()),
            exchange_positions,
        )
        order_ids_report = _compare_active_orders(
            local_store.orders.values(),
            _normalize_okx_order_identifiers(self.gateway.orders_pending()),
        )
        result = LiveReconcileResult(
            status="clean",
            positions_issues=positions_report.issues,
            missing_orders_on_exchange=order_ids_report["missing_on_exchange"],
            missing_orders_locally=order_ids_report["missing_locally"],
        )
        if not result.is_clean:
            return LiveReconcileResult(
                status="blocked",
                positions_issues=result.positions_issues,
                missing_orders_on_exchange=result.missing_orders_on_exchange,
                missing_orders_locally=result.missing_orders_locally,
            )
        return result


def _normalize_okx_positions(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = row.get("instId") or row.get("symbol")
        raw_size = row.get("pos") or row.get("size")
        if raw_size in {None, "", "0", "0.0"}:
            continue
        size = abs(Decimal(str(raw_size)))
        normalized.append(
            {
                "symbol": str(symbol) if symbol is not None else "",
                "direction": _okx_position_direction(row),
                "size": str(size),
            }
        )
    return normalized


def _okx_position_direction(row: dict[str, Any]) -> str:
    pos_side = row.get("posSide")
    if pos_side in {"long", "short"}:
        return str(pos_side)
    raw_size = row.get("pos") or row.get("size") or "0"
    return "short" if Decimal(str(raw_size)) < 0 else "long"


def _normalize_okx_order_identifiers(payload: dict[str, Any]) -> list[set[str]]:
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        return []
    order_identifiers: list[set[str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifiers: set[str] = set()
        order_id = row.get("ordId") or row.get("order_id")
        if order_id:
            identifiers.add(str(order_id))
        client_order_id = row.get("clOrdId") or row.get("client_order_id")
        if client_order_id:
            identifiers.add(str(client_order_id))
        if identifiers:
            order_identifiers.append(identifiers)
    return order_identifiers


def _active_local_order_identifiers(orders: Iterable[Order]) -> list[tuple[str, set[str]]]:
    order_identifiers: list[tuple[str, set[str]]] = []
    for order in orders:
        if order.status not in ACTIVE_LOCAL_ORDER_STATUSES:
            continue
        identifiers = {order.order_id}
        if order.client_order_id:
            identifiers.add(order.client_order_id)
        order_identifiers.append((order.order_id, identifiers))
    return order_identifiers


def _compare_active_orders(
    local_orders: Iterable[Order],
    exchange_order_identifiers: list[set[str]],
) -> dict[str, set[str]]:
    local_order_identifiers = _active_local_order_identifiers(local_orders)
    missing_on_exchange = {
        order_id
        for order_id, identifiers in local_order_identifiers
        if not any(identifiers & exchange_identifiers for exchange_identifiers in exchange_order_identifiers)
    }
    missing_locally = {
        _representative_order_identifier(exchange_identifiers)
        for exchange_identifiers in exchange_order_identifiers
        if not any(identifiers & exchange_identifiers for _, identifiers in local_order_identifiers)
    }
    return {
        "missing_on_exchange": missing_on_exchange,
        "missing_locally": missing_locally,
    }


def _representative_order_identifier(identifiers: set[str]) -> str:
    return sorted(identifiers)[0]
