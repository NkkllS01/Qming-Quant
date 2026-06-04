from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timedelta, timezone

from core.models import Candle, Fill, FundingRate, IndexPrice, Instrument, MarkPrice
from exchanges.okx.websocket import OKXWebSocketClient, OKXWebSocketConfig
from live.state import AccountBalance


class FakeGateway:
    def __init__(self) -> None:
        self.instrument_calls: list[str] = []
        self.candle_calls: list[dict] = []
        self.rest_positions: list[dict] = []
        self.rest_orders: list[dict] = []
        self.rest_fills: list[Fill] = []
        self.recent_fill_calls: list[dict] = []
        self.public_ws = OKXWebSocketClient(OKXWebSocketConfig())
        self.private_ws = OKXWebSocketClient(
            OKXWebSocketConfig(api_key="key", secret_key="secret", passphrase="pass")
        )

    def instruments(self, inst_type: str = "SWAP") -> list[Instrument]:
        self.instrument_calls.append(inst_type)
        return [
            Instrument(
                symbol="BTC-USDT-SWAP",
                inst_type="SWAP",
                tick_size=Decimal("0.1"),
                lot_size=Decimal("0.01"),
                min_size=Decimal("0.01"),
                state="live",
            )
        ]

    def history_candles(
        self,
        symbol: str,
        timeframe: str = "1m",
        *,
        after: str | None = None,
        before: str | None = None,
        limit: int = 300,
    ) -> list[Candle]:
        self.candle_calls.append(
            {"symbol": symbol, "timeframe": timeframe, "after": after, "before": before, "limit": limit}
        )
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=start + timedelta(minutes=i),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal(100 + i),
                volume=Decimal("10"),
                confirmed=True,
            )
            for i in range(3)
        ]

    def history_candles_range(
        self, symbol: str, timeframe: str, start_at: datetime, end_at: datetime
    ) -> list[Candle]:
        return [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=start_at + timedelta(minutes=i),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal(100 + i),
                volume=Decimal("10"),
                confirmed=True,
            )
            for i in range(int((end_at - start_at).total_seconds() // 60) + 1)
        ]

    def funding_rate_history(self, symbol: str, *, before: str | None = None, after: str | None = None, limit: int = 100):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return [
            FundingRate(
                symbol=symbol,
                funding_time=start + timedelta(hours=8 * i),
                funding_rate=Decimal("0.0001"),
                realized_rate=Decimal("0.00008"),
            )
            for i in range(limit)
        ]

    def mark_prices(self, inst_type: str = "SWAP", *, symbol: str | None = None):
        return [
            MarkPrice(
                symbol=symbol or "BTC-USDT-SWAP",
                mark_price=Decimal("70000.12"),
                updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ]

    def index_tickers(self, *, quote_currency: str | None = None, index_id: str | None = None):
        return [
            IndexPrice(
                index_id=index_id or f"BTC-{quote_currency or 'USDT'}",
                index_price=Decimal("69990.12"),
                updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ]

    def positions(self) -> dict:
        return {"data": self.rest_positions}

    def orders_pending(self) -> dict:
        return {"data": self.rest_orders}

    def recent_fills(
        self,
        *,
        account_id: str,
        inst_type: str = "SWAP",
        symbol: str | None = None,
        order_id: str | None = None,
        limit: int = 100,
    ) -> list[Fill]:
        self.recent_fill_calls.append(
            {
                "account_id": account_id,
                "inst_type": inst_type,
                "symbol": symbol,
                "order_id": order_id,
                "limit": limit,
            }
        )
        return self.rest_fills


def add_usdt_balance(store) -> None:
    store.upsert_balance(
        AccountBalance(
            currency="USDT",
            equity=Decimal("1000"),
            available=Decimal("900"),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
    )


def ma_crossover_candles(start: datetime) -> list[Candle]:
    closes = [Decimal("100") for _ in range(24)] + [
        Decimal("102"),
        Decimal("104"),
        Decimal("106"),
        Decimal("108"),
        Decimal("110"),
        Decimal("112"),
    ]
    return [
        Candle(
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            timestamp=start + timedelta(minutes=15 * idx),
            open=close,
            high=close + Decimal("1"),
            low=close - Decimal("1"),
            close=close,
            volume=Decimal("100"),
            confirmed=True,
        )
        for idx, close in enumerate(closes)
    ]
