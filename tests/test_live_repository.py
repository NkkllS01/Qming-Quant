from datetime import datetime, timezone
from decimal import Decimal

from core.models import Fill, Order, Position
from live.state import AccountBalance, LiveStateStore, LiveTicker
from storage.live_repository import LiveStateRepository


def test_live_state_repository_saves_and_loads_snapshot() -> None:
    repo = LiveStateRepository("sqlite:///:memory:")
    store = LiveStateStore()
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store.upsert_ticker(
        LiveTicker(
            symbol="BTC-USDT-SWAP",
            last_price=Decimal("70000"),
            mark_price=Decimal("70001"),
            updated_at=timestamp,
        )
    )
    store.upsert_balance(
        AccountBalance(
            currency="USDT",
            equity=Decimal("1000"),
            available=Decimal("900"),
            updated_at=timestamp,
        )
    )
    store.upsert_position(
        Position(
            account_id="okx_sub_main",
            symbol="BTC-USDT-SWAP",
            direction="long",
            size=Decimal("0.1"),
            entry_price=Decimal("69000"),
            mark_price=Decimal("70000"),
            unrealized_pnl=Decimal("100"),
            liquidation_price=Decimal("50000"),
            leverage=3,
            updated_at=timestamp,
        )
    )
    store.upsert_order(
        Order(
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id="btc_trend_15m",
            symbol="BTC-USDT-SWAP",
            run_id="live",
            order_id="okx-1",
            client_order_id="client-1",
            side="buy",
            order_type="market",
            size=Decimal("0.1"),
            filled_size=Decimal("0.1"),
            avg_fill_price=Decimal("69000"),
            status="filled",
            okx_order_id="okx-1",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    store.upsert_fill(
        Fill(
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id="btc_trend_15m",
            symbol="BTC-USDT-SWAP",
            run_id="live",
            fill_id="trade-1",
            client_order_id="client-1",
            side="buy",
            size=Decimal("0.04"),
            price=Decimal("69000"),
            fee=Decimal("-0.08"),
            created_at=timestamp,
        )
    )

    repo.save_snapshot(account_id="okx_sub_main", store=store)

    restored = repo.load_snapshot(account_id="okx_sub_main")
    assert restored.tickers["BTC-USDT-SWAP"].last_price == Decimal("70000")
    assert restored.tickers["BTC-USDT-SWAP"].mark_price == Decimal("70001")
    assert restored.balances["USDT"].equity == Decimal("1000")
    assert restored.positions["BTC-USDT-SWAP"].direction == "long"
    assert restored.positions["BTC-USDT-SWAP"].liquidation_price == Decimal("50000")
    assert restored.orders["okx-1"].status == "filled"
    assert restored.orders["okx-1"].avg_fill_price == Decimal("69000")
    assert restored.fills["trade-1"].size == Decimal("0.04")
    assert restored.fills["trade-1"].fee == Decimal("-0.08")


def test_live_state_repository_replaces_position_snapshot_for_account() -> None:
    repo = LiveStateRepository("sqlite:///:memory:")
    store = LiveStateStore()
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store.upsert_position(
        Position(
            account_id="okx_sub_main",
            symbol="ETH-USDT-SWAP",
            direction="short",
            size=Decimal("1"),
            entry_price=Decimal("3000"),
            mark_price=Decimal("2900"),
            updated_at=timestamp,
        )
    )
    repo.save_snapshot(account_id="okx_sub_main", store=store)

    repo.save_snapshot(account_id="okx_sub_main", store=LiveStateStore())

    restored = repo.load_snapshot(account_id="okx_sub_main")
    assert restored.positions == {}


def test_live_state_repository_keeps_fills_when_saving_empty_snapshot() -> None:
    repo = LiveStateRepository("sqlite:///:memory:")
    store = LiveStateStore()
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store.upsert_fill(
        Fill(
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id="btc_trend_15m",
            symbol="BTC-USDT-SWAP",
            run_id="live",
            fill_id="trade-1",
            client_order_id="client-1",
            side="buy",
            size=Decimal("0.04"),
            price=Decimal("69000"),
            fee=Decimal("-0.08"),
            created_at=timestamp,
        )
    )
    repo.save_snapshot(account_id="okx_sub_main", store=store)

    repo.save_snapshot(account_id="okx_sub_main", store=LiveStateStore())

    restored = repo.load_snapshot(account_id="okx_sub_main")
    assert restored.fills["trade-1"].price == Decimal("69000")
