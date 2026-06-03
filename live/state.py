from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from core.models import Order, Position, utc_from_ms


@dataclass(frozen=True)
class LiveTicker:
    symbol: str
    last_price: Decimal
    mark_price: Decimal | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class AccountBalance:
    currency: str
    equity: Decimal = Decimal("0")
    available: Decimal = Decimal("0")
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class LiveStateStore:
    def __init__(self) -> None:
        self.tickers: dict[str, LiveTicker] = {}
        self.balances: dict[str, AccountBalance] = {}
        self.positions: dict[str, Position] = {}
        self.orders: dict[str, Order] = {}
        self.last_event_at: datetime | None = None

    def upsert_ticker(self, ticker: LiveTicker) -> None:
        self.tickers[ticker.symbol] = ticker
        self.last_event_at = ticker.updated_at

    def upsert_balance(self, balance: AccountBalance) -> None:
        self.balances[balance.currency] = balance
        self.last_event_at = balance.updated_at

    def upsert_position(self, position: Position) -> None:
        if position.size == Decimal("0"):
            self.positions.pop(position.symbol, None)
        else:
            self.positions[position.symbol] = position
        self.last_event_at = position.updated_at

    def upsert_order(self, order: Order) -> None:
        self.orders[order.order_id] = order
        self.last_event_at = order.updated_at

    def snapshot(self) -> dict[str, Any]:
        return {
            "tickers": dict(self.tickers),
            "balances": dict(self.balances),
            "positions": dict(self.positions),
            "orders": dict(self.orders),
            "last_event_at": self.last_event_at,
        }


class OKXLiveStateHandler:
    def __init__(
        self,
        store: LiveStateStore,
        *,
        account_id: str,
        bot_id: str = "live_sync",
        strategy_id: str = "exchange_sync",
        run_id: str = "live",
    ) -> None:
        self.store = store
        self.account_id = account_id
        self.bot_id = bot_id
        self.strategy_id = strategy_id
        self.run_id = run_id

    async def handle(self, message: dict[str, Any]) -> None:
        channel = message.get("arg", {}).get("channel")
        data = message.get("data", [])
        if not isinstance(data, list):
            return
        if channel == "tickers":
            self._handle_tickers(data)
        elif channel == "account":
            self._handle_account(data)
        elif channel == "positions":
            self._handle_positions(data)
        elif channel == "orders":
            self._handle_orders(data)

    def _handle_tickers(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            symbol = row.get("instId")
            last = row.get("last")
            if not symbol or last in {None, ""}:
                continue
            self.store.upsert_ticker(
                LiveTicker(
                    symbol=symbol,
                    last_price=Decimal(str(last)),
                    mark_price=_optional_decimal(row.get("markPx")),
                    updated_at=_timestamp_from_row(row),
                )
            )

    def _handle_account(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            for detail in row.get("details", []):
                currency = detail.get("ccy")
                if not currency:
                    continue
                self.store.upsert_balance(
                    AccountBalance(
                        currency=currency,
                        equity=_decimal_or_zero(detail.get("eq")),
                        available=_decimal_or_zero(detail.get("availBal")),
                        updated_at=_timestamp_from_row(row),
                    )
                )

    def _handle_positions(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            symbol = row.get("instId")
            if not symbol:
                continue
            position = Position(
                account_id=self.account_id,
                symbol=symbol,
                direction=_position_direction(row),
                size=abs(_decimal_or_zero(row.get("pos"))),
                entry_price=_decimal_or_zero(row.get("avgPx")),
                mark_price=_decimal_or_zero(row.get("markPx")),
                unrealized_pnl=_decimal_or_zero(row.get("upl")),
                liquidation_price=_optional_decimal(row.get("liqPx")),
                margin_mode=row.get("mgnMode") or "isolated",
                leverage=int(_decimal_or_zero(row.get("lever")) or Decimal("1")),
                updated_at=_timestamp_from_row(row),
            )
            self.store.upsert_position(position)

    def _handle_orders(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            symbol = row.get("instId")
            order_id = row.get("ordId")
            if not symbol or not order_id:
                continue
            updated_at = _timestamp_from_row(row)
            self.store.upsert_order(
                Order(
                    account_id=self.account_id,
                    bot_id=self.bot_id,
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    run_id=self.run_id,
                    order_id=order_id,
                    client_order_id=row.get("clOrdId") or order_id,
                    side=row.get("side") or "unknown",
                    order_type=row.get("ordType") or "unknown",
                    size=_decimal_or_zero(row.get("sz")),
                    filled_size=_decimal_or_zero(row.get("accFillSz")),
                    price=_optional_decimal(row.get("px")),
                    avg_fill_price=_optional_decimal(row.get("avgPx")),
                    status=row.get("state") or "unknown",
                    okx_order_id=order_id,
                    created_at=_timestamp_from_row(row, "cTime"),
                    updated_at=updated_at,
                )
            )


def _timestamp_from_row(row: dict[str, Any], key: str = "uTime") -> datetime:
    value = row.get(key) or row.get("ts") or row.get("pTime")
    if value in {None, ""}:
        return datetime.now(timezone.utc)
    return utc_from_ms(value)


def _decimal_or_zero(value: Any) -> Decimal:
    if value in {None, ""}:
        return Decimal("0")
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    return Decimal(str(value))


def _position_direction(row: dict[str, Any]) -> str:
    pos_side = row.get("posSide")
    if pos_side in {"long", "short"}:
        return pos_side
    size = _decimal_or_zero(row.get("pos"))
    if size < 0:
        return "short"
    return "long"
