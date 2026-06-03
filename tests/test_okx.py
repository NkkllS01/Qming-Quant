import base64
import hashlib
import hmac
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx

from core.models import OrderIntent
from exchanges.okx.gateway import OKXGateway
from exchanges.okx.mapper import map_funding_rate, map_index_price, map_instrument, map_mark_price, map_okx_candles
from exchanges.okx.rest import OKXRestClient
from exchanges.okx.signer import sign_okx_request
from exchanges.okx.websocket import (
    OKX_WS_VERIFY_PATH,
    OKXWebSocketClient,
    OKXWebSocketConfig,
    OKXWebSocketRuntime,
    WebsocketsConnector,
    WebsocketsSession,
)
from tests.fakes import (
    FakeHttpResponse,
    FakeRawWebSocket,
    FakeWebSocketConnector,
    FakeWebSocketSender,
    FakeWebSocketSession,
)


def test_sign_okx_request_matches_hmac_sha256_base64() -> None:
    timestamp = "2020-12-08T09:08:57.715Z"
    method = "GET"
    request_path = "/api/v5/account/balance?ccy=BTC"
    body = ""
    secret = "22582BD0CFF14C41EDBF1AB98506286D"

    expected = base64.b64encode(
        hmac.new(
            secret.encode(),
            f"{timestamp}{method}{request_path}{body}".encode(),
            hashlib.sha256,
        ).digest()
    ).decode()

    assert sign_okx_request(timestamp, method, request_path, body, secret) == expected


def test_map_okx_candles_filters_unconfirmed_rows() -> None:
    rows = [
        ["1717200000000", "1", "2", "0.5", "1.5", "10", "1", "10", "1"],
        ["1717200060000", "2", "3", "1.5", "2.5", "20", "2", "20", "0"],
    ]

    candles = map_okx_candles("BTC-USDT-SWAP", "1m", rows, confirmed_only=True)

    assert len(candles) == 1
    assert candles[0].confirmed is True


def test_map_instrument_keeps_contract_precision_fields() -> None:
    instrument = map_instrument(
        {
            "instId": "BTC-USDT-SWAP",
            "instType": "SWAP",
            "baseCcy": "BTC",
            "quoteCcy": "USDT",
            "settleCcy": "USDT",
            "tickSz": "0.1",
            "lotSz": "0.01",
            "minSz": "0.01",
            "ctVal": "0.01",
            "state": "live",
        }
    )

    assert instrument.symbol == "BTC-USDT-SWAP"
    assert instrument.tick_size == Decimal("0.1")
    assert instrument.lot_size == Decimal("0.01")


def test_map_funding_rate_history_row_to_model() -> None:
    funding_rate = map_funding_rate(
        {
            "instId": "BTC-USDT-SWAP",
            "fundingRate": "0.0001",
            "realizedRate": "0.00008",
            "fundingTime": "1717200000000",
        }
    )

    assert funding_rate.symbol == "BTC-USDT-SWAP"
    assert funding_rate.funding_rate == Decimal("0.0001")
    assert funding_rate.realized_rate == Decimal("0.00008")
    assert funding_rate.funding_time.year == 2024


def test_map_mark_price_row_to_model() -> None:
    mark_price = map_mark_price(
        {
            "instId": "BTC-USDT-SWAP",
            "markPx": "70000.12",
            "ts": "1717200000000",
        }
    )

    assert mark_price.symbol == "BTC-USDT-SWAP"
    assert mark_price.mark_price == Decimal("70000.12")
    assert mark_price.updated_at.year == 2024


def test_map_index_price_row_to_model() -> None:
    index_price = map_index_price(
        {
            "instId": "BTC-USDT",
            "idxPx": "69990.12",
            "ts": "1717200000000",
        }
    )

    assert index_price.index_id == "BTC-USDT"
    assert index_price.index_price == Decimal("69990.12")
    assert index_price.updated_at.year == 2024


def test_okx_gateway_history_candles_range_paginates_until_start_is_covered() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows_by_after = {
        str(int((start + timedelta(minutes=5)).timestamp() * 1000)): [
            _okx_candle_row(start + timedelta(minutes=4), "104"),
            _okx_candle_row(start + timedelta(minutes=3), "103"),
        ],
        str(int((start + timedelta(minutes=3)).timestamp() * 1000)): [
            _okx_candle_row(start + timedelta(minutes=2), "102"),
            _okx_candle_row(start + timedelta(minutes=1), "101"),
        ],
    }
    rest = FakeRest(rows_by_after)
    gateway = OKXGateway(rest)

    candles = gateway.history_candles_range(
        "BTC-USDT-SWAP",
        "1m",
        start + timedelta(minutes=1),
        start + timedelta(minutes=5),
    )

    assert [candle.close for candle in candles] == [
        Decimal("101"),
        Decimal("102"),
        Decimal("103"),
        Decimal("104"),
    ]
    assert [call["after"] for call in rest.calls] == [
        str(int((start + timedelta(minutes=5)).timestamp() * 1000)),
        str(int((start + timedelta(minutes=3)).timestamp() * 1000)),
    ]


def test_okx_gateway_reads_mark_prices_with_optional_symbol() -> None:
    rest = FakeMarketPriceRest()
    gateway = OKXGateway(rest)

    prices = gateway.mark_prices("SWAP", symbol="BTC-USDT-SWAP")

    assert prices[0].symbol == "BTC-USDT-SWAP"
    assert prices[0].mark_price == Decimal("70000.12")
    assert rest.gets == [
        {
            "path": "/api/v5/public/mark-price",
            "params": {"instType": "SWAP", "instId": "BTC-USDT-SWAP"},
            "private": False,
        }
    ]


def test_okx_gateway_reads_index_tickers_with_quote_currency() -> None:
    rest = FakeMarketPriceRest()
    gateway = OKXGateway(rest)

    prices = gateway.index_tickers(quote_currency="USDT")

    assert prices[0].index_id == "BTC-USDT"
    assert prices[0].index_price == Decimal("69990.12")
    assert rest.gets == [
        {
            "path": "/api/v5/market/index-tickers",
            "params": {"quoteCcy": "USDT"},
            "private": False,
        }
    ]


def test_okx_websocket_config_builds_public_and_private_urls() -> None:
    config = OKXWebSocketConfig(base_url="wss://ws.okx.com:8443/")

    assert config.public_url == "wss://ws.okx.com:8443/ws/v5/public"
    assert config.private_url == "wss://ws.okx.com:8443/ws/v5/private"


def test_okx_websocket_login_message_uses_verify_signature() -> None:
    client = OKXWebSocketClient(
        OKXWebSocketConfig(api_key="key", secret_key="secret", passphrase="pass")
    )

    message = client.login_message(timestamp="1717200000")

    expected_sign = sign_okx_request("1717200000", "GET", OKX_WS_VERIFY_PATH, "", "secret")
    assert message == {
        "op": "login",
        "args": [
            {
                "apiKey": "key",
                "passphrase": "pass",
                "timestamp": "1717200000",
                "sign": expected_sign,
            }
        ],
    }


def test_okx_websocket_login_requires_credentials() -> None:
    client = OKXWebSocketClient(OKXWebSocketConfig())

    try:
        client.login_message(timestamp="1717200000")
    except ValueError as exc:
        assert "requires api_key" in str(exc)
    else:
        raise AssertionError("expected private login to require credentials")


def test_okx_websocket_subscribe_and_unsubscribe_messages() -> None:
    client = OKXWebSocketClient(OKXWebSocketConfig())
    channels = [{"channel": "candle15m", "instId": "BTC-USDT-SWAP"}]

    assert client.subscribe_message(channels, request_id="sub-1") == {
        "id": "sub-1",
        "op": "subscribe",
        "args": channels,
    }
    assert client.unsubscribe_message(channels) == {
        "op": "unsubscribe",
        "args": channels,
    }


def test_okx_websocket_sends_messages_through_injected_sender() -> None:
    async def run() -> None:
        sender = FakeWebSocketSender()
        client = OKXWebSocketClient(OKXWebSocketConfig(), sender=sender)
        await client.subscribe([{"channel": "positions", "instType": "SWAP"}], request_id="pos-1")

        assert sender.messages == [
            {
                "id": "pos-1",
                "op": "subscribe",
                "args": [{"channel": "positions", "instType": "SWAP"}],
            }
        ]

    asyncio.run(run())


def test_okx_gateway_exposes_configured_websocket_clients() -> None:
    rest = FakeRest({})
    public_ws = OKXWebSocketClient(OKXWebSocketConfig())
    private_ws = OKXWebSocketClient(OKXWebSocketConfig(api_key="key", secret_key="secret", passphrase="pass"))
    gateway = OKXGateway(rest, public_ws=public_ws, private_ws=private_ws)

    assert gateway.has_public_websocket is True
    assert gateway.has_private_websocket is True
    assert gateway.public_ws is public_ws
    assert gateway.private_ws is private_ws


def test_okx_rest_client_post_signs_compact_json_body(monkeypatch) -> None:
    captured: dict = {}
    client = StaticTimestampRestClient(
        api_key="key",
        secret_key="secret",
        passphrase="pass",
        base_url="https://example.test",
    )

    def fake_post(url, *, content, headers, timeout):
        captured.update({"url": url, "content": content, "headers": headers, "timeout": timeout})
        return FakeHttpResponse({"data": [{"ordId": "okx-1"}]})

    monkeypatch.setattr(httpx, "post", fake_post)

    response = client.post("/api/v5/trade/order", {"instId": "BTC-USDT-SWAP", "sz": "0.1"}, private=True)

    expected_body = '{"instId":"BTC-USDT-SWAP","sz":"0.1"}'
    expected_sign = sign_okx_request(
        "2024-01-01T00:00:00.000Z",
        "POST",
        "/api/v5/trade/order",
        expected_body,
        "secret",
    )
    assert response == {"data": [{"ordId": "okx-1"}]}
    assert captured["url"] == "https://example.test/api/v5/trade/order"
    assert captured["content"] == expected_body
    assert captured["headers"]["OK-ACCESS-SIGN"] == expected_sign


def test_okx_rest_client_adds_simulated_trading_header(monkeypatch) -> None:
    captured: dict = {}
    client = StaticTimestampRestClient(
        api_key="key",
        secret_key="secret",
        passphrase="pass",
        base_url="https://example.test",
        simulated_trading=True,
    )

    def fake_post(url, *, content, headers, timeout):
        captured.update({"headers": headers})
        return FakeHttpResponse({"data": [{"ordId": "okx-1"}]})

    monkeypatch.setattr(httpx, "post", fake_post)

    client.post("/api/v5/trade/order", {"instId": "BTC-USDT-SWAP"}, private=True)

    assert captured["headers"]["x-simulated-trading"] == "1"


def test_okx_gateway_places_order_from_order_intent() -> None:
    rest = FakeTradeRest()
    gateway = OKXGateway(rest)
    intent = _order_intent(price=None, reduce_only=True)

    response = gateway.place_order(intent, td_mode="isolated")

    assert response == {"data": [{"ordId": "okx-1"}]}
    assert rest.posts == [
        {
            "path": "/api/v5/trade/order",
            "body": {
                "instId": "BTC-USDT-SWAP",
                "tdMode": "isolated",
                "clOrdId": "client-1",
                "side": "buy",
                "ordType": "market",
                "sz": "0.1",
                "reduceOnly": "true",
            },
            "private": True,
        }
    ]


def test_okx_gateway_cancels_order_by_client_order_id() -> None:
    rest = FakeTradeRest()
    gateway = OKXGateway(rest)

    gateway.cancel_order(symbol="BTC-USDT-SWAP", client_order_id="client-1")

    assert rest.posts == [
        {
            "path": "/api/v5/trade/cancel-order",
            "body": {"instId": "BTC-USDT-SWAP", "clOrdId": "client-1"},
            "private": True,
        }
    ]


def test_okx_websocket_runtime_subscribes_and_dispatches_public_messages() -> None:
    async def run() -> None:
        received: list[dict] = []

        async def on_message(message: dict) -> None:
            received.append(message)

        session = FakeWebSocketSession([{"arg": {"channel": "candle15m"}, "data": [{"c": "100"}]}])
        connector = FakeWebSocketConnector([session])
        runtime = OKXWebSocketRuntime(
            OKXWebSocketClient(OKXWebSocketConfig()),
            connector=connector,
            channels=[{"channel": "candle15m", "instId": "BTC-USDT-SWAP"}],
            on_message=on_message,
        )

        count = await runtime.run_once(max_messages=1)

        assert count == 1
        assert connector.urls == ["wss://ws.okx.com:8443/ws/v5/public"]
        assert session.sent == [
            {
                "op": "subscribe",
                "args": [{"channel": "candle15m", "instId": "BTC-USDT-SWAP"}],
            }
        ]
        assert received == [{"arg": {"channel": "candle15m"}, "data": [{"c": "100"}]}]
        assert session.closed is True

    asyncio.run(run())


def test_okx_websocket_runtime_logs_in_before_private_subscriptions() -> None:
    async def run() -> None:
        session = FakeWebSocketSession([{"event": "subscribe", "arg": {"channel": "positions"}}])
        connector = FakeWebSocketConnector([session])
        runtime = OKXWebSocketRuntime(
            OKXWebSocketClient(
                OKXWebSocketConfig(api_key="key", secret_key="secret", passphrase="pass")
            ),
            connector=connector,
            private=True,
            channels=[{"channel": "positions", "instType": "SWAP"}],
        )

        await runtime.run_once(max_messages=1)

        assert connector.urls == ["wss://ws.okx.com:8443/ws/v5/private"]
        assert session.sent[0]["op"] == "login"
        assert session.sent[1] == {
            "op": "subscribe",
            "args": [{"channel": "positions", "instType": "SWAP"}],
        }

    asyncio.run(run())


def test_okx_websocket_runtime_replays_subscriptions_after_reconnect() -> None:
    async def run() -> None:
        first = FakeWebSocketSession([], fail_on_receive=True)
        second = FakeWebSocketSession([{"event": "subscribe", "arg": {"channel": "orders"}}])
        connector = FakeWebSocketConnector([first, second])
        delays: list[float] = []

        async def sleep(delay: float) -> None:
            delays.append(delay)

        runtime = OKXWebSocketRuntime(
            OKXWebSocketClient(
                OKXWebSocketConfig(api_key="key", secret_key="secret", passphrase="pass")
            ),
            connector=connector,
            private=True,
            channels=[{"channel": "orders", "instType": "SWAP"}],
        )

        count = await runtime.run_with_reconnects(
            max_reconnects=1,
            max_messages_per_connection=1,
            sleep=sleep,
            reconnect_delay=0.5,
        )

        assert count == 1
        assert delays == [0.5]
        assert len(connector.urls) == 2
        assert first.sent[0]["op"] == "login"
        assert first.sent[1]["op"] == "subscribe"
        assert second.sent[0]["op"] == "login"
        assert second.sent[1]["op"] == "subscribe"
        assert first.closed is True
        assert second.closed is True

    asyncio.run(run())


def test_websockets_session_sends_and_receives_json_objects() -> None:
    async def run() -> None:
        raw = FakeRawWebSocket(['{"event":"subscribe"}'])
        session = WebsocketsSession(raw)

        await session.send_json({"op": "subscribe", "args": [{"channel": "tickers"}]})
        received = await session.receive_json()
        await session.close()

        assert raw.sent == ['{"op":"subscribe","args":[{"channel":"tickers"}]}']
        assert received == {"event": "subscribe"}
        assert raw.closed is True

    asyncio.run(run())


def test_websockets_session_accepts_bytes_messages() -> None:
    async def run() -> None:
        raw = FakeRawWebSocket([b'{"event":"login"}'])
        session = WebsocketsSession(raw)

        assert await session.receive_json() == {"event": "login"}

    asyncio.run(run())


def test_websockets_session_rejects_non_object_messages() -> None:
    async def run() -> None:
        session = WebsocketsSession(FakeRawWebSocket(['["not-object"]']))

        try:
            await session.receive_json()
        except ValueError as exc:
            assert "JSON object" in str(exc)
        else:
            raise AssertionError("expected non-object websocket payload to be rejected")

    asyncio.run(run())


def test_websockets_connector_uses_injected_connect_factory() -> None:
    async def run() -> None:
        calls: list[str] = []
        raw = FakeRawWebSocket(['{"event":"ready"}'])

        async def connect(url: str) -> FakeRawWebSocket:
            calls.append(url)
            return raw

        connector = WebsocketsConnector(connect_factory=connect)
        session = await connector.connect("wss://example.test/ws")

        assert calls == ["wss://example.test/ws"]
        assert isinstance(session, WebsocketsSession)
        assert await session.receive_json() == {"event": "ready"}

    asyncio.run(run())


class FakeRest:
    def __init__(self, rows_by_after: dict[str, list[list[str]]]) -> None:
        self.rows_by_after = rows_by_after
        self.calls: list[dict] = []

    def get(self, path: str, params: dict | None = None, *, private: bool = False) -> dict:
        assert path == "/api/v5/market/history-candles"
        assert private is False
        assert params is not None
        self.calls.append(params)
        return {"data": self.rows_by_after.get(params["after"], [])}


class FakeTradeRest:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    def post(self, path: str, body: dict, *, private: bool = False) -> dict:
        self.posts.append({"path": path, "body": body, "private": private})
        return {"data": [{"ordId": "okx-1"}]}


class FakeMarketPriceRest:
    def __init__(self) -> None:
        self.gets: list[dict] = []

    def get(self, path: str, params: dict | None = None, *, private: bool = False) -> dict:
        self.gets.append({"path": path, "params": params, "private": private})
        if path == "/api/v5/public/mark-price":
            return {
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "markPx": "70000.12",
                        "ts": "1717200000000",
                    }
                ]
            }
        if path == "/api/v5/market/index-tickers":
            return {
                "data": [
                    {
                        "instId": "BTC-USDT",
                        "idxPx": "69990.12",
                        "ts": "1717200000000",
                    }
                ]
            }
        return {"data": []}


class StaticTimestampRestClient(OKXRestClient):
    def _timestamp(self) -> str:
        return "2024-01-01T00:00:00.000Z"


def _okx_candle_row(timestamp: datetime, close: str) -> list[str]:
    return [
        str(int(timestamp.timestamp() * 1000)),
        close,
        close,
        close,
        close,
        "10",
        "1",
        "10",
        "1",
    ]


def _order_intent(*, price: Decimal | None, reduce_only: bool) -> OrderIntent:
    return OrderIntent(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="live",
        side="buy",
        position_action="open",
        order_type="market" if price is None else "limit",
        size=Decimal("0.1"),
        price=price,
        reduce_only=reduce_only,
        client_order_id="client-1",
    )
