from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from exchanges.okx.signer import sign_okx_request


OKX_WS_VERIFY_PATH = "/users/self/verify"


class WebSocketSender(Protocol):
    async def send_json(self, message: dict[str, Any]) -> None: ...


class WebSocketSession(WebSocketSender, Protocol):
    async def receive_json(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class WebSocketConnector(Protocol):
    async def connect(self, url: str) -> WebSocketSession: ...


MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class OKXWebSocketConfig:
    api_key: str | None = None
    secret_key: str | None = None
    passphrase: str | None = None
    base_url: str = "wss://ws.okx.com:8443"

    @property
    def public_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/ws/v5/public"

    @property
    def private_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/ws/v5/private"

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.secret_key and self.passphrase)


class OKXWebSocketClient:
    def __init__(
        self,
        config: OKXWebSocketConfig,
        *,
        sender: WebSocketSender | None = None,
    ) -> None:
        self.config = config
        self.sender = sender

    def login_message(self, *, timestamp: str | None = None) -> dict[str, Any]:
        if not self.config.has_credentials:
            raise ValueError("OKX WebSocket private login requires api_key, secret_key, and passphrase")
        timestamp = timestamp or self._timestamp()
        sign = sign_okx_request(
            timestamp,
            "GET",
            OKX_WS_VERIFY_PATH,
            "",
            self.config.secret_key or "",
        )
        return {
            "op": "login",
            "args": [
                {
                    "apiKey": self.config.api_key,
                    "passphrase": self.config.passphrase,
                    "timestamp": timestamp,
                    "sign": sign,
                }
            ],
        }

    def subscribe_message(
        self,
        channels: list[dict[str, str]],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._subscription_message("subscribe", channels, request_id=request_id)

    def unsubscribe_message(
        self,
        channels: list[dict[str, str]],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._subscription_message("unsubscribe", channels, request_id=request_id)

    async def login(self) -> dict[str, Any]:
        message = self.login_message()
        await self._send(message)
        return message

    async def subscribe(
        self,
        channels: list[dict[str, str]],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        message = self.subscribe_message(channels, request_id=request_id)
        await self._send(message)
        return message

    async def unsubscribe(
        self,
        channels: list[dict[str, str]],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        message = self.unsubscribe_message(channels, request_id=request_id)
        await self._send(message)
        return message

    def _subscription_message(
        self,
        op: str,
        channels: list[dict[str, str]],
        *,
        request_id: str | None,
    ) -> dict[str, Any]:
        if not channels:
            raise ValueError("OKX WebSocket subscription requires at least one channel")
        message: dict[str, Any] = {"op": op, "args": channels}
        if request_id is not None:
            message["id"] = request_id
        return message

    async def _send(self, message: dict[str, Any]) -> None:
        if self.sender is None:
            raise RuntimeError("OKX WebSocket sender is not configured")
        await self.sender.send_json(message)

    def _timestamp(self) -> str:
        return str(int(datetime.now(timezone.utc).timestamp()))


class OKXWebSocketRuntime:
    def __init__(
        self,
        client: OKXWebSocketClient,
        *,
        connector: WebSocketConnector,
        private: bool = False,
        channels: list[dict[str, str]] | None = None,
        on_message: MessageHandler | None = None,
    ) -> None:
        self.client = client
        self.connector = connector
        self.private = private
        self.channels = list(channels or [])
        self.on_message = on_message

    @property
    def url(self) -> str:
        return self.client.config.private_url if self.private else self.client.config.public_url

    def add_subscription(self, channel: dict[str, str]) -> None:
        if channel not in self.channels:
            self.channels.append(channel)

    def remove_subscription(self, channel: dict[str, str]) -> None:
        self.channels = [item for item in self.channels if item != channel]

    async def run_once(self, *, max_messages: int | None = None) -> int:
        session = await self.connector.connect(self.url)
        received = 0
        try:
            if self.private:
                await session.send_json(self.client.login_message())
            if self.channels:
                await session.send_json(self.client.subscribe_message(self.channels))

            while max_messages is None or received < max_messages:
                message = await session.receive_json()
                received += 1
                if self.on_message is not None:
                    await self.on_message(message)
            return received
        finally:
            await session.close()

    async def run_with_reconnects(
        self,
        *,
        max_reconnects: int,
        max_messages_per_connection: int | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        reconnect_delay: float = 1.0,
    ) -> int:
        attempts = 0
        total_received = 0
        while True:
            try:
                total_received += await self.run_once(max_messages=max_messages_per_connection)
                return total_received
            except Exception:
                if attempts >= max_reconnects:
                    raise
                attempts += 1
                if sleep is not None:
                    await sleep(reconnect_delay)
