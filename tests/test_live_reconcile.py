from live.reconcile import LiveReconciliationService
from storage.live_repository import LiveStateRepository
from tests.fakes import FakePrivateGateway, live_store_with_position_and_order


def test_live_reconciliation_service_returns_clean_when_snapshots_match() -> None:
    repo = LiveStateRepository("sqlite:///:memory:")
    store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    repo.save_snapshot(account_id="okx_sub_main", store=store)

    result = LiveReconciliationService(
        gateway=FakePrivateGateway(
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
    store = live_store_with_position_and_order(order_id="local-only", direction="long", size="0.1")
    repo.save_snapshot(account_id="okx_sub_main", store=store)

    result = LiveReconciliationService(
        gateway=FakePrivateGateway(
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


def test_live_reconciliation_service_ignores_terminal_local_orders() -> None:
    repo = LiveStateRepository("sqlite:///:memory:")
    store = live_store_with_position_and_order(order_id="filled-order", direction="long", size="0.1")
    store.upsert_order(store.orders["filled-order"].model_copy(update={"status": "filled"}))
    repo.save_snapshot(account_id="okx_sub_main", store=store)

    result = LiveReconciliationService(
        gateway=FakePrivateGateway(
            positions=[{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}],
            orders=[],
        ),
        repository=repo,
        account_id="okx_sub_main",
    ).run()

    assert result.status == "clean"
    assert result.missing_orders_on_exchange == set()


def test_live_reconciliation_service_matches_active_order_by_client_order_id() -> None:
    repo = LiveStateRepository("sqlite:///:memory:")
    store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    store.upsert_order(store.orders["okx-1"].model_copy(update={"client_order_id": "client-1"}))
    repo.save_snapshot(account_id="okx_sub_main", store=store)

    result = LiveReconciliationService(
        gateway=FakePrivateGateway(
            positions=[{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}],
            orders=[{"clOrdId": "client-1"}],
        ),
        repository=repo,
        account_id="okx_sub_main",
    ).run()

    assert result.status == "clean"
    assert result.missing_orders_on_exchange == set()
    assert result.missing_orders_locally == set()
