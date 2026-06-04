from __future__ import annotations

from datetime import datetime

from core.models import Candle, Fill, FundingRate, IndexPrice, Instrument, MarkPrice, OrderIntent
from exchanges.okx.mapper import (
    map_funding_rate,
    map_index_price,
    map_instrument,
    map_mark_price,
    map_okx_candles,
    map_trade_fill,
)
from exchanges.okx.rest import OKXRestClient
from exchanges.okx.websocket import OKXWebSocketClient


class OKXGateway:
    def __init__(
        self,
        rest: OKXRestClient,
        *,
        public_ws: OKXWebSocketClient | None = None,
        private_ws: OKXWebSocketClient | None = None,
    ) -> None:
        self.rest = rest
        self.public_ws = public_ws
        self.private_ws = private_ws

    @property
    def has_public_websocket(self) -> bool:
        return self.public_ws is not None

    @property
    def has_private_websocket(self) -> bool:
        return self.private_ws is not None

    def server_time(self) -> dict:
        return self.rest.get("/api/v5/public/time")

    def instruments(self, inst_type: str = "SWAP") -> list[Instrument]:
        payload = self.rest.get("/api/v5/public/instruments", {"instType": inst_type})
        return [map_instrument(row) for row in payload.get("data", [])]

    def funding_rate_history(
        self,
        symbol: str,
        *,
        before: str | None = None,
        after: str | None = None,
        limit: int = 100,
    ) -> list[FundingRate]:
        params = {"instId": symbol, "limit": limit}
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        payload = self.rest.get("/api/v5/public/funding-rate-history", params)
        return [map_funding_rate(row) for row in payload.get("data", [])]

    def mark_prices(self, inst_type: str = "SWAP", *, symbol: str | None = None) -> list[MarkPrice]:
        params = {"instType": inst_type}
        if symbol is not None:
            params["instId"] = symbol
        payload = self.rest.get("/api/v5/public/mark-price", params)
        return [map_mark_price(row) for row in payload.get("data", [])]

    def index_tickers(self, *, quote_currency: str | None = None, index_id: str | None = None) -> list[IndexPrice]:
        params: dict[str, str] = {}
        if quote_currency is not None:
            params["quoteCcy"] = quote_currency
        if index_id is not None:
            params["instId"] = index_id
        payload = self.rest.get("/api/v5/market/index-tickers", params)
        return [map_index_price(row) for row in payload.get("data", [])]

    def history_candles(
        self,
        symbol: str,
        timeframe: str = "1m",
        *,
        after: str | None = None,
        before: str | None = None,
        limit: int = 300,
    ) -> list[Candle]:
        params = {"instId": symbol, "bar": timeframe, "limit": limit}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        payload = self.rest.get("/api/v5/market/history-candles", params)
        return map_okx_candles(symbol, timeframe, payload.get("data", []), confirmed_only=True)

    def history_candles_range(
        self,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[Candle]:
        cursor = str(int(end_at.timestamp() * 1000))
        candles_by_timestamp: dict[datetime, Candle] = {}
        while True:
            page = self.history_candles(symbol, timeframe, after=cursor, limit=300)
            if not page:
                break

            for candle in page:
                if start_at <= candle.timestamp <= end_at:
                    candles_by_timestamp[candle.timestamp] = candle

            oldest = min(candle.timestamp for candle in page)
            if oldest <= start_at:
                break

            next_cursor = str(int(oldest.timestamp() * 1000))
            if next_cursor == cursor:
                break
            cursor = next_cursor

        return sorted(candles_by_timestamp.values(), key=lambda candle: candle.timestamp)

    def balance(self) -> dict:
        return self.rest.get("/api/v5/account/balance", private=True)

    def positions(self) -> dict:
        return self.rest.get("/api/v5/account/positions", private=True)

    def orders_pending(self, inst_type: str = "SWAP") -> dict:
        return self.rest.get("/api/v5/trade/orders-pending", {"instType": inst_type}, private=True)

    def recent_fills(
        self,
        *,
        account_id: str,
        inst_type: str = "SWAP",
        symbol: str | None = None,
        order_id: str | None = None,
        after: str | None = None,
        before: str | None = None,
        limit: int = 100,
    ) -> list[Fill]:
        if limit < 1 or limit > 100:
            raise ValueError("recent_fills limit must be between 1 and 100")
        params: dict[str, str | int] = {"instType": inst_type, "limit": limit}
        if symbol is not None:
            params["instId"] = symbol
        if order_id is not None:
            params["ordId"] = order_id
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before
        payload = self.rest.get("/api/v5/trade/fills", params, private=True)
        return [map_trade_fill(row, account_id=account_id) for row in payload.get("data", [])]

    def place_order(self, intent: OrderIntent, *, td_mode: str = "isolated") -> dict:
        body = {
            "instId": intent.symbol,
            "tdMode": td_mode,
            "clOrdId": intent.client_order_id,
            "side": intent.side,
            "ordType": intent.order_type,
            "sz": str(intent.size),
        }
        if intent.price is not None:
            body["px"] = str(intent.price)
        if intent.reduce_only:
            body["reduceOnly"] = "true"
        return self.rest.post("/api/v5/trade/order", body, private=True)

    def cancel_order(self, *, symbol: str, order_id: str | None = None, client_order_id: str | None = None) -> dict:
        if order_id is None and client_order_id is None:
            raise ValueError("cancel_order requires order_id or client_order_id")
        body = {"instId": symbol}
        if order_id is not None:
            body["ordId"] = order_id
        if client_order_id is not None:
            body["clOrdId"] = client_order_id
        return self.rest.post("/api/v5/trade/cancel-order", body, private=True)
