from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, delete, select
from sqlalchemy.engine import Engine

from core.models import Fill, Order, Position
from live.state import AccountBalance, LiveStateStore, LiveTicker
from storage.db import ensure_utc, upsert_rows


class LiveStateRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self.tickers = Table(
            "live_tickers",
            self.metadata,
            Column("symbol", String, primary_key=True),
            Column("last_price", String, nullable=False),
            Column("mark_price", String, nullable=True),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.balances = Table(
            "live_balances",
            self.metadata,
            Column("account_id", String, primary_key=True),
            Column("currency", String, primary_key=True),
            Column("equity", String, nullable=False),
            Column("available", String, nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.positions = Table(
            "live_positions",
            self.metadata,
            Column("account_id", String, primary_key=True),
            Column("symbol", String, primary_key=True),
            Column("direction", String, nullable=False),
            Column("size", String, nullable=False),
            Column("entry_price", String, nullable=False),
            Column("mark_price", String, nullable=False),
            Column("unrealized_pnl", String, nullable=False),
            Column("liquidation_price", String, nullable=True),
            Column("margin_mode", String, nullable=False),
            Column("leverage", String, nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.orders = Table(
            "live_orders",
            self.metadata,
            Column("account_id", String, primary_key=True),
            Column("order_id", String, primary_key=True),
            Column("bot_id", String, nullable=False),
            Column("strategy_id", String, nullable=False),
            Column("symbol", String, nullable=False),
            Column("run_id", String, nullable=False),
            Column("client_order_id", String, nullable=False),
            Column("side", String, nullable=False),
            Column("order_type", String, nullable=False),
            Column("size", String, nullable=False),
            Column("filled_size", String, nullable=False),
            Column("price", String, nullable=True),
            Column("avg_fill_price", String, nullable=True),
            Column("status", String, nullable=False),
            Column("okx_order_id", String, nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.fills = Table(
            "live_fills",
            self.metadata,
            Column("account_id", String, primary_key=True),
            Column("fill_id", String, primary_key=True),
            Column("bot_id", String, nullable=False),
            Column("strategy_id", String, nullable=False),
            Column("symbol", String, nullable=False),
            Column("run_id", String, nullable=False),
            Column("client_order_id", String, nullable=False),
            Column("side", String, nullable=False),
            Column("size", String, nullable=False),
            Column("price", String, nullable=False),
            Column("fee", String, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self.metadata.create_all(self.engine)

    def save_snapshot(self, *, account_id: str, store: LiveStateStore) -> None:
        with self.engine.begin() as conn:
            if store.tickers:
                upsert_rows(conn, self.tickers, [_ticker_row(ticker) for ticker in store.tickers.values()], ["symbol"])
            if store.balances:
                upsert_rows(
                    conn,
                    self.balances,
                    [_balance_row(account_id, balance) for balance in store.balances.values()],
                    ["account_id", "currency"],
                )
            conn.execute(delete(self.positions).where(self.positions.c.account_id == account_id))
            if store.positions:
                upsert_rows(
                    conn,
                    self.positions,
                    [_position_row(position) for position in store.positions.values()],
                    ["account_id", "symbol"],
                )
            if store.orders:
                upsert_rows(
                    conn,
                    self.orders,
                    [_order_row(order) for order in store.orders.values()],
                    ["account_id", "order_id"],
                )
            if store.fills:
                upsert_rows(
                    conn,
                    self.fills,
                    [_fill_row(fill) for fill in store.fills.values()],
                    ["account_id", "fill_id"],
                )

    def load_snapshot(self, *, account_id: str) -> LiveStateStore:
        store = LiveStateStore()
        with self.engine.begin() as conn:
            ticker_rows = conn.execute(select(self.tickers)).mappings().all()
            balance_rows = conn.execute(
                select(self.balances).where(self.balances.c.account_id == account_id)
            ).mappings().all()
            position_rows = conn.execute(
                select(self.positions).where(self.positions.c.account_id == account_id)
            ).mappings().all()
            order_rows = conn.execute(select(self.orders).where(self.orders.c.account_id == account_id)).mappings().all()
            fill_rows = conn.execute(
                select(self.fills).where(self.fills.c.account_id == account_id).order_by(self.fills.c.created_at)
            ).mappings().all()
        for row in ticker_rows:
            store.upsert_ticker(_ticker_from_row(row))
        for row in balance_rows:
            store.upsert_balance(_balance_from_row(row))
        for row in position_rows:
            store.upsert_position(_position_from_row(row))
        for row in order_rows:
            store.upsert_order(_order_from_row(row))
        for row in fill_rows:
            store.upsert_fill(_fill_from_row(row))
        return store


def _ticker_row(ticker: LiveTicker) -> dict:
    return {
        "symbol": ticker.symbol,
        "last_price": str(ticker.last_price),
        "mark_price": str(ticker.mark_price) if ticker.mark_price is not None else None,
        "updated_at": ticker.updated_at,
    }


def _balance_row(account_id: str, balance: AccountBalance) -> dict:
    return {
        "account_id": account_id,
        "currency": balance.currency,
        "equity": str(balance.equity),
        "available": str(balance.available),
        "updated_at": balance.updated_at,
    }


def _position_row(position: Position) -> dict:
    return {
        "account_id": position.account_id,
        "symbol": position.symbol,
        "direction": position.direction,
        "size": str(position.size),
        "entry_price": str(position.entry_price),
        "mark_price": str(position.mark_price),
        "unrealized_pnl": str(position.unrealized_pnl),
        "liquidation_price": str(position.liquidation_price) if position.liquidation_price is not None else None,
        "margin_mode": position.margin_mode,
        "leverage": str(position.leverage),
        "updated_at": position.updated_at,
    }


def _order_row(order: Order) -> dict:
    return {
        "account_id": order.account_id,
        "order_id": order.order_id,
        "bot_id": order.bot_id,
        "strategy_id": order.strategy_id,
        "symbol": order.symbol,
        "run_id": order.run_id,
        "client_order_id": order.client_order_id,
        "side": order.side,
        "order_type": order.order_type,
        "size": str(order.size),
        "filled_size": str(order.filled_size),
        "price": str(order.price) if order.price is not None else None,
        "avg_fill_price": str(order.avg_fill_price) if order.avg_fill_price is not None else None,
        "status": order.status,
        "okx_order_id": order.okx_order_id,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def _fill_row(fill: Fill) -> dict:
    return {
        "account_id": fill.account_id,
        "fill_id": fill.fill_id,
        "bot_id": fill.bot_id,
        "strategy_id": fill.strategy_id,
        "symbol": fill.symbol,
        "run_id": fill.run_id,
        "client_order_id": fill.client_order_id,
        "side": fill.side,
        "size": str(fill.size),
        "price": str(fill.price),
        "fee": str(fill.fee),
        "created_at": fill.created_at,
    }


def _ticker_from_row(row) -> LiveTicker:
    return LiveTicker(
        symbol=row["symbol"],
        last_price=Decimal(row["last_price"]),
        mark_price=Decimal(row["mark_price"]) if row["mark_price"] is not None else None,
        updated_at=ensure_utc(row["updated_at"]),
    )


def _balance_from_row(row) -> AccountBalance:
    return AccountBalance(
        currency=row["currency"],
        equity=Decimal(row["equity"]),
        available=Decimal(row["available"]),
        updated_at=ensure_utc(row["updated_at"]),
    )


def _position_from_row(row) -> Position:
    return Position(
        account_id=row["account_id"],
        symbol=row["symbol"],
        direction=row["direction"],
        size=Decimal(row["size"]),
        entry_price=Decimal(row["entry_price"]),
        mark_price=Decimal(row["mark_price"]),
        unrealized_pnl=Decimal(row["unrealized_pnl"]),
        liquidation_price=Decimal(row["liquidation_price"]) if row["liquidation_price"] is not None else None,
        margin_mode=row["margin_mode"],
        leverage=int(row["leverage"]),
        updated_at=ensure_utc(row["updated_at"]),
    )


def _order_from_row(row) -> Order:
    return Order(
        account_id=row["account_id"],
        bot_id=row["bot_id"],
        strategy_id=row["strategy_id"],
        symbol=row["symbol"],
        run_id=row["run_id"],
        order_id=row["order_id"],
        client_order_id=row["client_order_id"],
        side=row["side"],
        order_type=row["order_type"],
        size=Decimal(row["size"]),
        filled_size=Decimal(row["filled_size"]),
        price=Decimal(row["price"]) if row["price"] is not None else None,
        avg_fill_price=Decimal(row["avg_fill_price"]) if row["avg_fill_price"] is not None else None,
        status=row["status"],
        okx_order_id=row["okx_order_id"],
        created_at=ensure_utc(row["created_at"]),
        updated_at=ensure_utc(row["updated_at"]),
    )


def _fill_from_row(row) -> Fill:
    return Fill(
        account_id=row["account_id"],
        bot_id=row["bot_id"],
        strategy_id=row["strategy_id"],
        symbol=row["symbol"],
        run_id=row["run_id"],
        fill_id=row["fill_id"],
        client_order_id=row["client_order_id"],
        side=row["side"],
        size=Decimal(row["size"]),
        price=Decimal(row["price"]),
        fee=Decimal(row["fee"]),
        created_at=ensure_utc(row["created_at"]),
    )
