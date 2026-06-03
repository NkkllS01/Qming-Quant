from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from execution.reconciliation import Reconciliation, ReconciliationIssue
from storage.live_repository import LiveStateRepository


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
        order_ids_report = self.reconciliation.compare_order_ids(
            set(local_store.orders),
            _normalize_okx_order_ids(self.gateway.orders_pending()),
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


def _normalize_okx_order_ids(payload: dict[str, Any]) -> set[str]:
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        return set()
    order_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        order_id = row.get("ordId") or row.get("order_id")
        if order_id:
            order_ids.add(str(order_id))
    return order_ids
