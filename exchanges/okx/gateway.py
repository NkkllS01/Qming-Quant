from __future__ import annotations

from datetime import datetime

from core.models import Candle, FundingRate, Instrument
from exchanges.okx.mapper import map_funding_rate, map_instrument, map_okx_candles
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
