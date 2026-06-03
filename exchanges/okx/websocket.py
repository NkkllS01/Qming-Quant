from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from exchanges.okx.signer import sign_okx_request


OKX_WS_VERIFY_PATH = "/users/self/verify"


class WebSocketSender(Protocol):
    async def send_json(self, message: dict[str, Any]) -> None: ...


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
