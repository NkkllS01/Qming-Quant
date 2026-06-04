from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Column, DateTime, MetaData, Numeric, String, Table, create_engine, select
from sqlalchemy.engine import Engine

from storage.db import ensure_utc


@dataclass(frozen=True)
class LiveIntentJournalEntry:
    run_id: str
    event_index: int
    account_id: str
    bot_id: str
    strategy_id: str
    symbol: str
    timeframe: str
    signal_action: str
    signal_direction: str
    signal_reason: str
    client_order_id: str
    side: str
    position_action: str
    order_type: str
    size: Decimal
    price: Decimal | None
    status: str
    risk_reason: str
    policy_reason: str
    gate_reason: str
    created_at: datetime


class LiveIntentRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self.live_intent_journal = Table(
            "live_intent_journal",
            self.metadata,
            Column("run_id", String, primary_key=True),
            Column("event_index", String, primary_key=True),
            Column("account_id", String, nullable=False),
            Column("bot_id", String, nullable=False),
            Column("strategy_id", String, nullable=False),
            Column("symbol", String, nullable=False),
            Column("timeframe", String, nullable=False),
            Column("signal_action", String, nullable=False),
            Column("signal_direction", String, nullable=False),
            Column("signal_reason", String, nullable=False),
            Column("client_order_id", String, nullable=False),
            Column("side", String, nullable=False),
            Column("position_action", String, nullable=False),
            Column("order_type", String, nullable=False),
            Column("size", Numeric(38, 18), nullable=False),
            Column("price", Numeric(38, 18), nullable=True),
            Column("status", String, nullable=False),
            Column("risk_reason", String, nullable=False),
            Column("policy_reason", String, nullable=False),
            Column("gate_reason", String, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self.metadata.create_all(self.engine)

    def append(self, entry: LiveIntentJournalEntry) -> None:
        row = {
            "run_id": entry.run_id,
            "event_index": str(entry.event_index),
            "account_id": entry.account_id,
            "bot_id": entry.bot_id,
            "strategy_id": entry.strategy_id,
            "symbol": entry.symbol,
            "timeframe": entry.timeframe,
            "signal_action": entry.signal_action,
            "signal_direction": entry.signal_direction,
            "signal_reason": entry.signal_reason,
            "client_order_id": entry.client_order_id,
            "side": entry.side,
            "position_action": entry.position_action,
            "order_type": entry.order_type,
            "size": entry.size,
            "price": entry.price,
            "status": entry.status,
            "risk_reason": entry.risk_reason,
            "policy_reason": entry.policy_reason,
            "gate_reason": entry.gate_reason,
            "created_at": entry.created_at,
        }
        with self.engine.begin() as conn:
            conn.execute(self.live_intent_journal.insert(), [row])

    def list_entries(self, run_id: str | None = None) -> list[LiveIntentJournalEntry]:
        stmt = select(self.live_intent_journal)
        if run_id is not None:
            stmt = stmt.where(self.live_intent_journal.c.run_id == run_id)
        stmt = stmt.order_by(self.live_intent_journal.c.run_id, self.live_intent_journal.c.event_index)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_entry_from_row(row) for row in rows]


def _entry_from_row(row) -> LiveIntentJournalEntry:
    return LiveIntentJournalEntry(
        run_id=row["run_id"],
        event_index=int(row["event_index"]),
        account_id=row["account_id"],
        bot_id=row["bot_id"],
        strategy_id=row["strategy_id"],
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        signal_action=row["signal_action"],
        signal_direction=row["signal_direction"],
        signal_reason=row["signal_reason"],
        client_order_id=row["client_order_id"],
        side=row["side"],
        position_action=row["position_action"],
        order_type=row["order_type"],
        size=Decimal(row["size"]),
        price=Decimal(row["price"]) if row["price"] is not None else None,
        status=row["status"],
        risk_reason=row["risk_reason"],
        policy_reason=row["policy_reason"],
        gate_reason=row["gate_reason"],
        created_at=ensure_utc(row["created_at"]),
    )


def live_intent_entry(
    *,
    run_id: str,
    event_index: int,
    account_id: str,
    bot_id: str,
    strategy_id: str,
    symbol: str,
    timeframe: str,
    signal_action: str,
    signal_direction: str,
    signal_reason: str,
    client_order_id: str,
    side: str,
    position_action: str,
    order_type: str,
    size: Decimal,
    price: Decimal | None,
    status: str,
    risk_reason: str,
    policy_reason: str,
    gate_reason: str,
) -> LiveIntentJournalEntry:
    return LiveIntentJournalEntry(
        run_id=run_id,
        event_index=event_index,
        account_id=account_id,
        bot_id=bot_id,
        strategy_id=strategy_id,
        symbol=symbol,
        timeframe=timeframe,
        signal_action=signal_action,
        signal_direction=signal_direction,
        signal_reason=signal_reason,
        client_order_id=client_order_id,
        side=side,
        position_action=position_action,
        order_type=order_type,
        size=size,
        price=price,
        status=status,
        risk_reason=risk_reason,
        policy_reason=policy_reason,
        gate_reason=gate_reason,
        created_at=datetime.now(timezone.utc),
    )
