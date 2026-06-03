from datetime import datetime, timezone
from decimal import Decimal

from core.models import Order, Position
from live.reconcile import LiveReconciliationService
from live.state import LiveStateStore
from storage.live_repository import LiveStateRepository


def test_live_reconciliation_service_returns_clean_when_snapshots_match() -> None:
    repo = LiveStateRepository("sqlite:///:memory:")
    store = LiveStateStore()
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store.upsert_position(
        Position(
            account_id="okx_sub_main",
            symbol="BTC-USDT-SWAP",
            direction="long",
            size=Decimal("0.1"),
            entry_price=Decimal("70000"),
            mark_price=Decimal("70100"),
            updated_at=timestamp,
        )
    )
    store.upsert_order(
        Order(
            account_id="okx_sub_main",
            bot_id="live_sync",
            strategy_id="exchange_sync",
            symbol="BTC-USDT-SWAP",
            run_id="live",
            order_id="okx-1",
            client_order_id="client-1",
            side="buy",
            order_type="limit",
            size=Decimal("0.1"),
            status="live",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    repo.save_snapshot(account_id="okx_sub_main", store=store)

    result = LiveReconciliationService(
        gateway=FakeGateway(
            positions=[{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}],
            orders=[{"ordId": "okx-1"}],
        ),
        repository=repo,
        account_id="okx_sub_main",
    ).run()

    assert result.status == "clean"
    assert result.is_clean is True


def test_live_reconciliation_service_blocks_on_position_and_order_mismatches() -> None:
    repo = LiveStateRepository("sqlite:///:memory:")
    store = LiveStateStore()
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store.upsert_position(
        Position(
            account_id="okx_sub_main",
            symbol="BTC-USDT-SWAP",
            direction="long",
            size=Decimal("0.1"),
            entry_price=Decimal("70000"),
            mark_price=Decimal("70100"),
            updated_at=timestamp,
        )
    )
    store.upsert_order(
        Order(
            account_id="okx_sub_main",
            bot_id="live_sync",
            strategy_id="exchange_sync",
            symbol="BTC-USDT-SWAP",
            run_id="live",
            order_id="local-only",
            client_order_id="client-1",
            side="buy",
            order_type="limit",
            size=Decimal("0.1"),
            status="live",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    repo.save_snapshot(account_id="okx_sub_main", store=store)

    result = LiveReconciliationService(
        gateway=FakeGateway(
            positions=[{"instId": "BTC-USDT-SWAP", "posSide": "short", "pos": "-0.2"}],
            orders=[{"ordId": "exchange-only"}],
        ),
        repository=repo,
        account_id="okx_sub_main",
    ).run()

    assert result.status == "blocked"
    assert result.is_clean is False
    assert {issue.kind for issue in result.positions_issues} == {"size_mismatch", "direction_mismatch"}
    assert result.missing_orders_on_exchange == {"local-only"}
    assert result.missing_orders_locally == {"exchange-only"}


class FakeGateway:
    def __init__(self, *, positions: list[dict], orders: list[dict]) -> None:
        self._positions = positions
        self._orders = orders

    def positions(self) -> dict:
        return {"data": self._positions}

    def orders_pending(self) -> dict:
        return {"data": self._orders}
