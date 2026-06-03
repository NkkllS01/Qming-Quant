from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Column, DateTime, MetaData, Numeric, String, Table, create_engine, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from core.models import Fill, PaperJournalEvent, Position


class TradeRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self.fills = Table(
            "fills",
            self.metadata,
            Column("run_id", String, primary_key=True),
            Column("fill_id", String, primary_key=True),
            Column("account_id", String, nullable=False),
            Column("bot_id", String, nullable=False),
            Column("strategy_id", String, nullable=False),
            Column("symbol", String, nullable=False),
            Column("client_order_id", String, nullable=False),
            Column("side", String, nullable=False),
            Column("size", Numeric(38, 18), nullable=False),
            Column("price", Numeric(38, 18), nullable=False),
            Column("fee", Numeric(38, 18), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self.positions = Table(
            "positions",
            self.metadata,
            Column("run_id", String, primary_key=True),
            Column("account_id", String, primary_key=True),
            Column("symbol", String, primary_key=True),
            Column("direction", String, nullable=False),
            Column("size", Numeric(38, 18), nullable=False),
            Column("entry_price", Numeric(38, 18), nullable=False),
            Column("mark_price", Numeric(38, 18), nullable=False),
            Column("unrealized_pnl", Numeric(38, 18), nullable=False),
            Column("margin_mode", String, nullable=False),
            Column("leverage", String, nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.journal = Table(
            "paper_journal",
            self.metadata,
            Column("run_id", String, primary_key=True),
            Column("event_index", String, primary_key=True),
            Column("event_type", String, nullable=False),
            Column("symbol", String, nullable=False),
            Column("strategy_id", String, nullable=False),
            Column("message", String, nullable=False),
            Column("timestamp", DateTime(timezone=True), nullable=False),
        )
        self.metadata.create_all(self.engine)

    def save_paper_run(
        self,
        *,
        run_id: str,
        fills: list[Fill],
        positions: list[Position],
        journal: list[PaperJournalEvent],
    ) -> None:
        self._delete_run_snapshot(run_id)
        self._upsert_fills(fills)
        self._upsert_positions(run_id, positions)
        self._upsert_journal(run_id, journal)

    def _delete_run_snapshot(self, run_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(self.fills).where(self.fills.c.run_id == run_id))
            conn.execute(delete(self.positions).where(self.positions.c.run_id == run_id))
            conn.execute(delete(self.journal).where(self.journal.c.run_id == run_id))

    def _upsert_fills(self, fills: list[Fill]) -> None:
        if not fills:
            return
        rows = [
            {
                "run_id": fill.run_id,
                "fill_id": fill.fill_id,
                "account_id": fill.account_id,
                "bot_id": fill.bot_id,
                "strategy_id": fill.strategy_id,
                "symbol": fill.symbol,
                "client_order_id": fill.client_order_id,
                "side": fill.side,
                "size": fill.size,
                "price": fill.price,
                "fee": fill.fee,
                "created_at": fill.created_at,
            }
            for fill in fills
        ]
        stmt = sqlite_insert(self.fills).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["run_id", "fill_id"],
            set_={
                "account_id": stmt.excluded.account_id,
                "bot_id": stmt.excluded.bot_id,
                "strategy_id": stmt.excluded.strategy_id,
                "symbol": stmt.excluded.symbol,
                "client_order_id": stmt.excluded.client_order_id,
                "side": stmt.excluded.side,
                "size": stmt.excluded.size,
                "price": stmt.excluded.price,
                "fee": stmt.excluded.fee,
                "created_at": stmt.excluded.created_at,
            },
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def _upsert_positions(self, run_id: str, positions: list[Position]) -> None:
        if not positions:
            return
        rows = [
            {
                "run_id": run_id,
                "account_id": position.account_id,
                "symbol": position.symbol,
                "direction": position.direction,
                "size": position.size,
                "entry_price": position.entry_price,
                "mark_price": position.mark_price,
                "unrealized_pnl": position.unrealized_pnl,
                "margin_mode": position.margin_mode,
                "leverage": str(position.leverage),
                "updated_at": position.updated_at,
            }
            for position in positions
        ]
        stmt = sqlite_insert(self.positions).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["run_id", "account_id", "symbol"],
            set_={
                "direction": stmt.excluded.direction,
                "size": stmt.excluded.size,
                "entry_price": stmt.excluded.entry_price,
                "mark_price": stmt.excluded.mark_price,
                "unrealized_pnl": stmt.excluded.unrealized_pnl,
                "margin_mode": stmt.excluded.margin_mode,
                "leverage": stmt.excluded.leverage,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def _upsert_journal(self, run_id: str, journal: list[PaperJournalEvent]) -> None:
        if not journal:
            return
        rows = [
            {
                "run_id": run_id,
                "event_index": str(index),
                "event_type": event.event_type,
                "symbol": event.symbol,
                "strategy_id": event.strategy_id,
                "message": event.message,
                "timestamp": event.timestamp,
            }
            for index, event in enumerate(journal)
        ]
        stmt = sqlite_insert(self.journal).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["run_id", "event_index"],
            set_={
                "event_type": stmt.excluded.event_type,
                "symbol": stmt.excluded.symbol,
                "strategy_id": stmt.excluded.strategy_id,
                "message": stmt.excluded.message,
                "timestamp": stmt.excluded.timestamp,
            },
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def list_fills(self, run_id: str) -> list[Fill]:
        stmt = select(self.fills).where(self.fills.c.run_id == run_id).order_by(self.fills.c.created_at)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [
            Fill(
                account_id=row["account_id"],
                bot_id=row["bot_id"],
                strategy_id=row["strategy_id"],
                symbol=row["symbol"],
                run_id=row["run_id"],
                fill_id=row["fill_id"],
                client_order_id=row["client_order_id"],
                side=row["side"],
                size=_decimal(row["size"]),
                price=_decimal(row["price"]),
                fee=_decimal(row["fee"]),
                created_at=_ensure_utc(row["created_at"]),
            )
            for row in rows
        ]

    def list_positions(self, run_id: str) -> list[Position]:
        stmt = select(self.positions).where(self.positions.c.run_id == run_id).order_by(self.positions.c.symbol)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [
            Position(
                account_id=row["account_id"],
                symbol=row["symbol"],
                direction=row["direction"],
                size=_decimal(row["size"]),
                entry_price=_decimal(row["entry_price"]),
                mark_price=_decimal(row["mark_price"]),
                unrealized_pnl=_decimal(row["unrealized_pnl"]),
                margin_mode=row["margin_mode"],
                leverage=int(row["leverage"]),
                updated_at=_ensure_utc(row["updated_at"]),
            )
            for row in rows
        ]

    def list_journal(self, run_id: str) -> list[PaperJournalEvent]:
        stmt = select(self.journal).where(self.journal.c.run_id == run_id).order_by(self.journal.c.event_index)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [
            PaperJournalEvent(
                event_type=row["event_type"],
                symbol=row["symbol"],
                strategy_id=row["strategy_id"],
                message=row["message"],
                timestamp=_ensure_utc(row["timestamp"]),
            )
            for row in rows
        ]


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decimal(value) -> Decimal:
    rounded = Decimal(str(value)).quantize(Decimal("0.000000000001"))
    return rounded.quantize(Decimal("0.000000000000000001"))
