from __future__ import annotations

from dataclasses import dataclass

from exchanges.okx.gateway import OKXGateway
from exchanges.okx.websocket import OKXWebSocketRuntime, WebSocketConnector
from live.state import LiveStateStore, OKXLiveStateHandler


@dataclass(frozen=True)
class LiveSyncResult:
    public_messages: int
    private_messages: int
    tickers_count: int
    balances_count: int
    positions_count: int
    orders_count: int
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
    ) -> None:
        self.gateway = gateway
        self.connector = connector
        self.account_id = account_id
        self.symbols = symbols
        self.store = store or LiveStateStore()
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
                channels=_private_channels(),
                on_message=self.handler.handle,
            )
            private_messages = await runtime.run_once(max_messages=max_messages_per_connection)

        return LiveSyncResult(
            public_messages=public_messages,
            private_messages=private_messages,
            tickers_count=len(self.store.tickers),
            balances_count=len(self.store.balances),
            positions_count=len(self.store.positions),
            orders_count=len(self.store.orders),
        )


def _public_channels(symbols: list[str]) -> list[dict[str, str]]:
    return [{"channel": "tickers", "instId": symbol} for symbol in symbols]


def _private_channels() -> list[dict[str, str]]:
    return [
        {"channel": "account"},
        {"channel": "positions", "instType": "SWAP"},
        {"channel": "orders", "instType": "SWAP"},
    ]
