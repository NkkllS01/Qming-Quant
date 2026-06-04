from __future__ import annotations

from dataclasses import dataclass

from core.models import Fill
from live.state import LiveStateStore
from storage.live_repository import LiveStateRepository


@dataclass(frozen=True)
class FillSyncResult:
    fetched_count: int
    stored_count: int
    matched_count: int


class LiveFillSyncService:
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

    def run(
        self,
        *,
        inst_type: str = "SWAP",
        symbol: str | None = None,
        order_id: str | None = None,
        limit: int = 100,
    ) -> FillSyncResult:
        store = self.repository.load_snapshot(account_id=self.account_id)
        fills = self.gateway.recent_fills(
            account_id=self.account_id,
            inst_type=inst_type,
            symbol=symbol,
            order_id=order_id,
            limit=limit,
        )
        matched_count = 0
        for fill in fills:
            matched_fill = _with_order_lineage(fill, store)
            if matched_fill is not fill:
                matched_count += 1
            store.upsert_fill(matched_fill)
        self.repository.save_snapshot(account_id=self.account_id, store=store)
        return FillSyncResult(
            fetched_count=len(fills),
            stored_count=len(fills),
            matched_count=matched_count,
        )


def _with_order_lineage(fill: Fill, store: LiveStateStore) -> Fill:
    order = store.find_order(order_id=fill.client_order_id, client_order_id=fill.client_order_id)
    if order is None:
        return fill
    return fill.model_copy(
        update={
            "account_id": order.account_id,
            "bot_id": order.bot_id,
            "strategy_id": order.strategy_id,
            "run_id": order.run_id,
        }
    )
