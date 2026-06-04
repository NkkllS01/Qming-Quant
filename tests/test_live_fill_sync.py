from datetime import datetime, timezone
from decimal import Decimal

from core.models import Fill, Order
from live.fill_sync import LiveFillSyncService
from live.state import LiveStateStore
from storage.live_repository import LiveStateRepository


def test_live_fill_sync_persists_recent_rest_fills_with_order_lineage() -> None:
    repo = LiveStateRepository("sqlite:///:memory:")
    store = LiveStateStore()
    store.upsert_order(
        Order(
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id="btc_trend_15m",
            symbol="BTC-USDT-SWAP",
            run_id="live-run",
            order_id="okx-1",
            client_order_id="client-1",
            side="buy",
            order_type="market",
            size=Decimal("0.1"),
            status="filled",
        )
    )
    repo.save_snapshot(account_id="okx_sub_main", store=store)
    gateway = FakeFillGateway(
        [
            Fill(
                account_id="okx_sub_main",
                bot_id="live_sync",
                strategy_id="exchange_sync",
                symbol="BTC-USDT-SWAP",
                run_id="live",
                fill_id="trade-1",
                client_order_id="client-1",
                side="buy",
                size=Decimal("0.03"),
                price=Decimal("70200"),
                fee=Decimal("-0.08"),
                created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            )
        ]
    )
    service = LiveFillSyncService(gateway=gateway, repository=repo, account_id="okx_sub_main")

    result = service.run(symbol="BTC-USDT-SWAP", limit=50)

    assert result.fetched_count == 1
    assert result.stored_count == 1
    assert result.matched_count == 1
    restored = repo.load_snapshot(account_id="okx_sub_main")
    fill = restored.fills["trade-1"]
    assert fill.bot_id == "okx_perp_bot_main"
    assert fill.strategy_id == "btc_trend_15m"
    assert fill.run_id == "live-run"
    assert gateway.calls == [
        {
            "account_id": "okx_sub_main",
            "inst_type": "SWAP",
            "symbol": "BTC-USDT-SWAP",
            "order_id": None,
            "limit": 50,
        }
    ]


def test_live_fill_sync_matches_order_id_when_client_id_is_missing() -> None:
    repo = LiveStateRepository("sqlite:///:memory:")
    store = LiveStateStore()
    store.upsert_order(
        Order(
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id="btc_trend_15m",
            symbol="BTC-USDT-SWAP",
            run_id="live-run",
            order_id="okx-1",
            client_order_id="client-1",
            side="buy",
            order_type="market",
            size=Decimal("0.1"),
            status="filled",
        )
    )
    repo.save_snapshot(account_id="okx_sub_main", store=store)
    gateway = FakeFillGateway(
        [
            Fill(
                account_id="okx_sub_main",
                bot_id="live_sync",
                strategy_id="exchange_sync",
                symbol="BTC-USDT-SWAP",
                run_id="live",
                fill_id="trade-2",
                client_order_id="okx-1",
                side="buy",
                size=Decimal("0.02"),
                price=Decimal("70300"),
                created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            )
        ]
    )

    result = LiveFillSyncService(
        gateway=gateway,
        repository=repo,
        account_id="okx_sub_main",
    ).run(symbol="BTC-USDT-SWAP")

    assert result.matched_count == 1
    fill = repo.load_snapshot(account_id="okx_sub_main").fills["trade-2"]
    assert fill.bot_id == "okx_perp_bot_main"
    assert fill.strategy_id == "btc_trend_15m"


class FakeFillGateway:
    def __init__(self, fills: list[Fill]) -> None:
        self.fills = fills
        self.calls: list[dict] = []

    def recent_fills(
        self,
        *,
        account_id: str,
        inst_type: str = "SWAP",
        symbol: str | None = None,
        order_id: str | None = None,
        limit: int = 100,
    ) -> list[Fill]:
        self.calls.append(
            {
                "account_id": account_id,
                "inst_type": inst_type,
                "symbol": symbol,
                "order_id": order_id,
                "limit": limit,
            }
        )
        return self.fills
