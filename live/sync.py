from __future__ import annotations

from dataclasses import dataclass

from exchanges.okx.gateway import OKXGateway
from exchanges.okx.websocket import OKXWebSocketRuntime, WebSocketConnector
from live.state import LiveStateStore, OKXLiveStateHandler
from storage.live_repository import LiveStateRepository


@dataclass(frozen=True)
class LiveSyncResult:
    public_messages: int
    private_messages: int
    tickers_count: int
    balances_count: int
    positions_count: int
    orders_count: int
    fills_count: int
    persisted: bool = False
    trading_enabled: bool = False


class LiveSyncService:
    def __init__(
        self,
        *,
        gateway: OKXGateway,
        connector: WebSocketConnector,
        account_id: str,
        symbols: list[str],
        store: LiveStateStore | None = None,
        repository: LiveStateRepository | None = None,
        include_fills_channel: bool = False,
    ) -> None:
        self.gateway = gateway
        self.connector = connector
        self.account_id = account_id
        self.symbols = symbols
        self.store = store or LiveStateStore()
        self.repository = repository
        self.include_fills_channel = include_fills_channel
        self.handler = OKXLiveStateHandler(self.store, account_id=account_id)

    async def run_once(
        self,
        *,
        include_public: bool = True,
        include_private: bool = True,
        max_messages_per_connection: int = 1,
    ) -> LiveSyncResult:
        public_messages = 0
        private_messages = 0

        if include_public:
            public_ws = self.gateway.public_ws
            if public_ws is None:
                raise RuntimeError("OKX public WebSocket client is not configured")
            runtime = OKXWebSocketRuntime(
                public_ws,
                connector=self.connector,
                channels=_public_channels(self.symbols),
                on_message=self.handler.handle,
            )
            public_messages = await runtime.run_once(max_messages=max_messages_per_connection)

        if include_private:
            private_ws = self.gateway.private_ws
            if private_ws is None:
                raise RuntimeError("OKX private WebSocket client is not configured")
            runtime = OKXWebSocketRuntime(
                private_ws,
                connector=self.connector,
                private=True,
                channels=_private_channels(self.symbols, include_fills_channel=self.include_fills_channel),
                on_message=self.handler.handle,
            )
            private_messages = await runtime.run_once(max_messages=max_messages_per_connection)

        persisted = False
        if self.repository is not None:
            self.repository.save_snapshot(account_id=self.account_id, store=self.store)
            persisted = True

        return LiveSyncResult(
            public_messages=public_messages,
            private_messages=private_messages,
            tickers_count=len(self.store.tickers),
            balances_count=len(self.store.balances),
            positions_count=len(self.store.positions),
            orders_count=len(self.store.orders),
            fills_count=len(self.store.fills),
            persisted=persisted,
        )


def _public_channels(symbols: list[str]) -> list[dict[str, str]]:
    return [{"channel": "tickers", "instId": symbol} for symbol in symbols]


def _private_channels(symbols: list[str], *, include_fills_channel: bool = False) -> list[dict[str, str]]:
    channels = [
        {"channel": "account"},
        {"channel": "positions", "instType": "SWAP"},
        {"channel": "orders", "instType": "SWAP"},
    ]
    if include_fills_channel:
        channels.extend({"channel": "fills", "instId": symbol} for symbol in symbols)
    return channels
