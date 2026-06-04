import asyncio
from decimal import Decimal

from core.models import Fill, Order
from live.state import AccountBalance, LiveStateStore, LiveTicker, OKXLiveStateHandler


def test_live_state_store_upserts_and_snapshots_state() -> None:
    store = LiveStateStore()

    store.upsert_ticker(LiveTicker(symbol="BTC-USDT-SWAP", last_price=Decimal("70000")))
    store.upsert_balance(AccountBalance(currency="USDT", equity=Decimal("1000")))

    snapshot = store.snapshot()
    assert snapshot["tickers"]["BTC-USDT-SWAP"].last_price == Decimal("70000")
    assert snapshot["balances"]["USDT"].equity == Decimal("1000")
    assert snapshot["last_event_at"] is not None


def test_okx_live_state_handler_updates_ticker_and_account_balance() -> None:
    async def run() -> None:
        store = LiveStateStore()
        handler = OKXLiveStateHandler(store, account_id="okx_sub_main")

        await handler.handle(
            {
                "arg": {"channel": "tickers"},
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "last": "70100.5",
                        "markPx": "70101",
                        "ts": "1717200000000",
                    }
                ],
            }
        )
        await handler.handle(
            {
                "arg": {"channel": "account"},
                "data": [
                    {
                        "uTime": "1717200001000",
                        "details": [{"ccy": "USDT", "eq": "1000.5", "availBal": "900.25"}],
                    }
                ],
            }
        )

        assert store.tickers["BTC-USDT-SWAP"].last_price == Decimal("70100.5")
        assert store.tickers["BTC-USDT-SWAP"].mark_price == Decimal("70101")
        assert store.balances["USDT"].equity == Decimal("1000.5")
        assert store.balances["USDT"].available == Decimal("900.25")

    asyncio.run(run())


def test_okx_live_state_handler_normalizes_positions_and_removes_zero_position() -> None:
    async def run() -> None:
        store = LiveStateStore()
        handler = OKXLiveStateHandler(store, account_id="okx_sub_main")

        await handler.handle(
            {
                "arg": {"channel": "positions"},
                "data": [
                    {
                        "instId": "ETH-USDT-SWAP",
                        "posSide": "net",
                        "pos": "-2",
                        "avgPx": "3000",
                        "markPx": "2990",
                        "upl": "-20",
                        "liqPx": "2500",
                        "mgnMode": "isolated",
                        "lever": "3",
                        "uTime": "1717200000000",
                    }
                ],
            }
        )

        position = store.positions["ETH-USDT-SWAP"]
        assert position.account_id == "okx_sub_main"
        assert position.direction == "short"
        assert position.size == Decimal("2")
        assert position.entry_price == Decimal("3000")
        assert position.mark_price == Decimal("2990")
        assert position.unrealized_pnl == Decimal("-20")
        assert position.liquidation_price == Decimal("2500")
        assert position.leverage == 3

        await handler.handle(
            {
                "arg": {"channel": "positions"},
                "data": [
                    {
                        "instId": "ETH-USDT-SWAP",
                        "posSide": "net",
                        "pos": "0",
                        "avgPx": "",
                        "markPx": "3010",
                        "upl": "",
                        "uTime": "1717200001000",
                    }
                ],
            }
        )

        assert "ETH-USDT-SWAP" not in store.positions

    asyncio.run(run())


def test_okx_live_state_handler_updates_orders_with_lineage() -> None:
    async def run() -> None:
        store = LiveStateStore()
        handler = OKXLiveStateHandler(
            store,
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id="btc_trend_15m",
            run_id="live-run",
        )

        await handler.handle(
            {
                "arg": {"channel": "orders"},
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "ordId": "okx-1",
                        "clOrdId": "client-1",
                        "side": "buy",
                        "ordType": "market",
                        "sz": "0.1",
                        "accFillSz": "0.06",
                        "avgPx": "70000",
                        "state": "partially_filled",
                        "cTime": "1717200000000",
                        "uTime": "1717200001000",
                    }
                ],
            }
        )

        order = store.orders["okx-1"]
        assert order.account_id == "okx_sub_main"
        assert order.bot_id == "okx_perp_bot_main"
        assert order.strategy_id == "btc_trend_15m"
        assert order.run_id == "live-run"
        assert order.client_order_id == "client-1"
        assert order.size == Decimal("0.1")
        assert order.filled_size == Decimal("0.06")
        assert order.avg_fill_price == Decimal("70000")
        assert order.status == "partially_filled"

    asyncio.run(run())


def test_live_state_store_preserves_order_lineage_on_exchange_update() -> None:
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
            status="submitted",
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
            order_type="market",
            size=Decimal("0.1"),
            filled_size=Decimal("0.1"),
            avg_fill_price=Decimal("70100"),
            status="filled",
        )
    )

    order = store.orders["okx-1"]
    assert order.bot_id == "okx_perp_bot_main"
    assert order.strategy_id == "btc_trend_15m"
    assert order.run_id == "live-run"
    assert order.status == "filled"
    assert order.filled_size == Decimal("0.1")
    assert order.avg_fill_price == Decimal("70100")


def test_live_state_store_rekeys_order_when_exchange_order_id_arrives() -> None:
    store = LiveStateStore()
    store.upsert_order(
        Order(
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id="btc_trend_15m",
            symbol="BTC-USDT-SWAP",
            run_id="live-run",
            order_id="client-1",
            client_order_id="client-1",
            side="buy",
            order_type="market",
            size=Decimal("0.1"),
            status="submitted",
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
            order_type="market",
            size=Decimal("0.1"),
            status="live",
            okx_order_id="okx-1",
        )
    )

    assert "client-1" not in store.orders
    order = store.orders["okx-1"]
    assert order.bot_id == "okx_perp_bot_main"
    assert order.strategy_id == "btc_trend_15m"
    assert order.run_id == "live-run"
    assert order.okx_order_id == "okx-1"


def test_okx_live_state_handler_records_fill_from_order_update() -> None:
    async def run() -> None:
        store = LiveStateStore()
        handler = OKXLiveStateHandler(
            store,
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id="btc_trend_15m",
            run_id="live-run",
        )

        await handler.handle(
            {
                "arg": {"channel": "orders"},
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "ordId": "okx-1",
                        "clOrdId": "client-1",
                        "tradeId": "trade-1",
                        "side": "buy",
                        "ordType": "market",
                        "sz": "0.1",
                        "accFillSz": "0.1",
                        "fillSz": "0.04",
                        "fillPx": "70100",
                        "fillFee": "-0.12",
                        "avgPx": "70100",
                        "state": "filled",
                        "fillTime": "1717200002000",
                        "cTime": "1717200000000",
                        "uTime": "1717200002000",
                    }
                ],
            }
        )

        fill = store.fills["trade-1"]
        assert fill.account_id == "okx_sub_main"
        assert fill.bot_id == "okx_perp_bot_main"
        assert fill.strategy_id == "btc_trend_15m"
        assert fill.run_id == "live-run"
        assert fill.client_order_id == "client-1"
        assert fill.side == "buy"
        assert fill.size == Decimal("0.04")
        assert fill.price == Decimal("70100")
        assert fill.fee == Decimal("-0.12")

    asyncio.run(run())


def test_okx_live_state_handler_records_fill_with_existing_order_lineage() -> None:
    async def run() -> None:
        store = LiveStateStore()
        store.upsert_order(
            Order(
                account_id="okx_sub_main",
                bot_id="okx_perp_bot_main",
                strategy_id="btc_trend_15m",
                symbol="BTC-USDT-SWAP",
                run_id="live-run",
                order_id="client-1",
                client_order_id="client-1",
                side="buy",
                order_type="market",
                size=Decimal("0.1"),
                status="submitted",
            )
        )
        handler = OKXLiveStateHandler(store, account_id="okx_sub_main")

        await handler.handle(
            {
                "arg": {"channel": "orders"},
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "ordId": "okx-1",
                        "clOrdId": "client-1",
                        "tradeId": "trade-1",
                        "side": "buy",
                        "ordType": "market",
                        "sz": "0.1",
                        "accFillSz": "0.1",
                        "fillSz": "0.1",
                        "fillPx": "70100",
                        "fillFee": "-0.12",
                        "avgPx": "70100",
                        "state": "filled",
                        "fillTime": "1717200002000",
                        "cTime": "1717200000000",
                        "uTime": "1717200002000",
                    }
                ],
            }
        )

        fill = store.fills["trade-1"]
        assert fill.bot_id == "okx_perp_bot_main"
        assert fill.strategy_id == "btc_trend_15m"
        assert fill.run_id == "live-run"
        assert "client-1" not in store.orders
        assert store.orders["okx-1"].bot_id == "okx_perp_bot_main"

    asyncio.run(run())


def test_okx_live_state_handler_records_private_fills_channel_with_existing_order_lineage() -> None:
    async def run() -> None:
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
                status="submitted",
            )
        )
        handler = OKXLiveStateHandler(store, account_id="okx_sub_main")

        await handler.handle(
            {
                "arg": {"channel": "fills", "instId": "BTC-USDT-SWAP"},
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "ordId": "okx-1",
                        "clOrdId": "client-1",
                        "tradeId": "trade-2",
                        "side": "buy",
                        "fillSz": "0.03",
                        "fillPx": "70200",
                        "ts": "1717200003000",
                    }
                ],
            }
        )

        fill = store.fills["trade-2"]
        assert fill.account_id == "okx_sub_main"
        assert fill.bot_id == "okx_perp_bot_main"
        assert fill.strategy_id == "btc_trend_15m"
        assert fill.run_id == "live-run"
        assert fill.client_order_id == "client-1"
        assert fill.size == Decimal("0.03")
        assert fill.price == Decimal("70200")
        assert fill.fee == Decimal("0")

    asyncio.run(run())


def test_okx_live_state_handler_uses_order_id_when_fills_channel_client_id_is_zero() -> None:
    async def run() -> None:
        store = LiveStateStore()
        handler = OKXLiveStateHandler(store, account_id="okx_sub_main")

        await handler.handle(
            {
                "arg": {"channel": "fills", "instId": "BTC-USDT-SWAP"},
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "ordId": "okx-1",
                        "clOrdId": "0",
                        "tradeId": "trade-3",
                        "side": "sell",
                        "fillSz": "0.02",
                        "fillPx": "70300",
                        "ts": "1717200004000",
                    }
                ],
            }
        )

        fill = store.fills["trade-3"]
        assert fill.client_order_id == "okx-1"
        assert fill.bot_id == "live_sync"
        assert fill.strategy_id == "exchange_sync"

    asyncio.run(run())


def test_order_update_can_upgrade_generic_fill_lineage_from_fills_channel() -> None:
    async def run() -> None:
        store = LiveStateStore()
        store.upsert_order(
            Order(
                account_id="okx_sub_main",
                bot_id="okx_perp_bot_main",
                strategy_id="btc_trend_15m",
                symbol="BTC-USDT-SWAP",
                run_id="live-run",
                order_id="client-1",
                client_order_id="client-1",
                side="buy",
                order_type="market",
                size=Decimal("0.1"),
                status="submitted",
            )
        )
        handler = OKXLiveStateHandler(store, account_id="okx_sub_main")

        await handler.handle(
            {
                "arg": {"channel": "fills", "instId": "BTC-USDT-SWAP"},
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "ordId": "okx-1",
                        "clOrdId": "0",
                        "tradeId": "trade-4",
                        "side": "buy",
                        "fillSz": "0.05",
                        "fillPx": "70400",
                        "ts": "1717200005000",
                    }
                ],
            }
        )
        assert store.fills["trade-4"].bot_id == "live_sync"

        await handler.handle(
            {
                "arg": {"channel": "orders"},
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "ordId": "okx-1",
                        "clOrdId": "client-1",
                        "tradeId": "trade-4",
                        "side": "buy",
                        "ordType": "market",
                        "sz": "0.1",
                        "accFillSz": "0.05",
                        "fillSz": "0.05",
                        "fillPx": "70400",
                        "fillFee": "-0.15",
                        "avgPx": "70400",
                        "state": "partially_filled",
                        "fillTime": "1717200005000",
                        "cTime": "1717200000000",
                        "uTime": "1717200005000",
                    }
                ],
            }
        )

        fill = store.fills["trade-4"]
        assert fill.bot_id == "okx_perp_bot_main"
        assert fill.strategy_id == "btc_trend_15m"
        assert fill.run_id == "live-run"
        assert fill.client_order_id == "client-1"
        assert fill.fee == Decimal("-0.15")

    asyncio.run(run())


def test_live_state_store_preserves_existing_fill_lineage_on_repeat_update() -> None:
    store = LiveStateStore()
    store.upsert_fill(
        _fill(
            fill_id="trade-1",
            bot_id="okx_perp_bot_main",
            strategy_id="btc_trend_15m",
            run_id="live-run",
        )
    )

    store.upsert_fill(
        _fill(
            fill_id="trade-1",
            bot_id="live_sync",
            strategy_id="exchange_sync",
            run_id="live",
        )
    )

    fill = store.fills["trade-1"]
    assert fill.bot_id == "okx_perp_bot_main"
    assert fill.strategy_id == "btc_trend_15m"
    assert fill.run_id == "live-run"


def test_okx_live_state_handler_ignores_unknown_or_malformed_messages() -> None:
    async def run() -> None:
        store = LiveStateStore()
        handler = OKXLiveStateHandler(store, account_id="okx_sub_main")

        await handler.handle({"arg": {"channel": "unknown"}, "data": [{"foo": "bar"}]})
        await handler.handle({"arg": {"channel": "tickers"}, "data": {"not": "a-list"}})
        await handler.handle({"arg": {"channel": "orders"}, "data": [{"instId": "BTC-USDT-SWAP"}]})

        assert store.snapshot()["tickers"] == {}
        assert store.snapshot()["orders"] == {}

    asyncio.run(run())


def _fill(*, fill_id: str, bot_id: str, strategy_id: str, run_id: str):
    return Fill(
        account_id="okx_sub_main",
        bot_id=bot_id,
        strategy_id=strategy_id,
        symbol="BTC-USDT-SWAP",
        run_id=run_id,
        fill_id=fill_id,
        client_order_id="client-1",
        side="buy",
        size=Decimal("0.1"),
        price=Decimal("70100"),
    )
