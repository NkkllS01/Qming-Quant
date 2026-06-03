from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from core.models import Order, Position
from live.state import LiveStateStore


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeWebSocketSession:
    def __init__(self, messages: list[dict], *, fail_on_receive: bool = False) -> None:
        self.messages = list(messages)
        self.fail_on_receive = fail_on_receive
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def receive_json(self) -> dict:
        if self.fail_on_receive:
            raise ConnectionError("disconnected")
        if not self.messages:
            raise ConnectionError("no more messages")
        return self.messages.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeWebSocketConnector:
    def __init__(self, sessions: list[FakeWebSocketSession]) -> None:
        self.sessions = list(sessions)
        self.urls: list[str] = []

    async def connect(self, url: str) -> FakeWebSocketSession:
        self.urls.append(url)
        if not self.sessions:
            raise ConnectionError("no session available")
        return self.sessions.pop(0)


class FakeRawWebSocket:
    def __init__(self, messages: list[str | bytes]) -> None:
        self.messages = list(messages)
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str | bytes:
        if not self.messages:
            raise ConnectionError("no more raw messages")
        return self.messages.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeWebSocketSender:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


def live_store_with_position_and_order(*, order_id: str, direction: str, size: str) -> LiveStateStore:
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store = LiveStateStore()
    store.upsert_position(
        Position(
            account_id="okx_sub_main",
            symbol="BTC-USDT-SWAP",
            direction=direction,
            size=Decimal(size),
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
            order_id=order_id,
            client_order_id=order_id,
            side="buy",
            order_type="limit",
            size=Decimal("0.1"),
            status="live",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    return store


class FakePrivateGateway:
    def __init__(self, *, positions: list[dict[str, Any]], orders: list[dict[str, Any]]) -> None:
        self._positions = positions
        self._orders = orders

    def positions(self) -> dict:
        return {"data": self._positions}

    def orders_pending(self) -> dict:
        return {"data": self._orders}
