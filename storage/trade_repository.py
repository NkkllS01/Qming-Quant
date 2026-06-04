from __future__ import annotations

from sqlalchemy import Column, DateTime, MetaData, Numeric, String, Table, create_engine, delete, select
from sqlalchemy.engine import Engine

from core.models import Fill, Position, SimulationJournalEvent
from storage.db import decimal_from_db, ensure_utc, upsert_rows


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
            "simulation_journal",
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

    def save_simulation_run(
        self,
        *,
        run_id: str,
        fills: list[Fill],
        positions: list[Position],
        journal: list[SimulationJournalEvent],
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
        with self.engine.begin() as conn:
            upsert_rows(conn, self.fills, rows, ["run_id", "fill_id"])

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
        with self.engine.begin() as conn:
            upsert_rows(conn, self.positions, rows, ["run_id", "account_id", "symbol"])

    def _upsert_journal(self, run_id: str, journal: list[SimulationJournalEvent]) -> None:
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
        with self.engine.begin() as conn:
            upsert_rows(conn, self.journal, rows, ["run_id", "event_index"])

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
                size=decimal_from_db(row["size"]),
                price=decimal_from_db(row["price"]),
                fee=decimal_from_db(row["fee"]),
                created_at=ensure_utc(row["created_at"]),
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
                size=decimal_from_db(row["size"]),
                entry_price=decimal_from_db(row["entry_price"]),
                mark_price=decimal_from_db(row["mark_price"]),
                unrealized_pnl=decimal_from_db(row["unrealized_pnl"]),
                margin_mode=row["margin_mode"],
                leverage=int(row["leverage"]),
                updated_at=ensure_utc(row["updated_at"]),
            )
            for row in rows
        ]

    def list_journal(self, run_id: str) -> list[SimulationJournalEvent]:
        stmt = select(self.journal).where(self.journal.c.run_id == run_id).order_by(self.journal.c.event_index)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [
            SimulationJournalEvent(
                event_type=row["event_type"],
                symbol=row["symbol"],
                strategy_id=row["strategy_id"],
                message=row["message"],
                timestamp=ensure_utc(row["timestamp"]),
            )
            for row in rows
        ]
