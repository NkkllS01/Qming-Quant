from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, create_engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class PauseState:
    account_id: str
    paused: bool
    reason: str
    updated_at: datetime


@dataclass(frozen=True)
class EquityRiskState:
    account_id: str
    currency: str
    day: str
    daily_equity_baseline: Decimal
    peak_equity: Decimal
    updated_at: datetime


class SafetyRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self.pause_state = Table(
            "safety_pause_state",
            self.metadata,
            Column("account_id", String, primary_key=True),
            Column("paused", Boolean, nullable=False),
            Column("reason", String, nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.equity_risk_state = Table(
            "safety_equity_risk_state",
            self.metadata,
            Column("account_id", String, primary_key=True),
            Column("currency", String, primary_key=True),
            Column("day", String, nullable=False),
            Column("daily_equity_baseline", String, nullable=False),
            Column("peak_equity", String, nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.metadata.create_all(self.engine)

    def set_pause(self, *, account_id: str, paused: bool, reason: str) -> PauseState:
        state = PauseState(
            account_id=account_id,
            paused=paused,
            reason=reason,
            updated_at=datetime.now(timezone.utc),
        )
        stmt = sqlite_insert(self.pause_state).values(
            {
                "account_id": state.account_id,
                "paused": state.paused,
                "reason": state.reason,
                "updated_at": state.updated_at,
            }
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["account_id"],
            set_={
                "paused": stmt.excluded.paused,
                "reason": stmt.excluded.reason,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)
        return state

    def get_pause(self, *, account_id: str) -> PauseState:
        stmt = select(self.pause_state).where(self.pause_state.c.account_id == account_id)
        with self.engine.begin() as conn:
            row = conn.execute(stmt).mappings().first()
        if row is None:
            return PauseState(
                account_id=account_id,
                paused=False,
                reason="not_paused",
                updated_at=datetime.fromtimestamp(0, tz=timezone.utc),
            )
        return PauseState(
            account_id=row["account_id"],
            paused=row["paused"],
            reason=row["reason"],
            updated_at=_ensure_utc(row["updated_at"]),
        )

    def upsert_equity_risk_state(self, state: EquityRiskState) -> EquityRiskState:
        stmt = sqlite_insert(self.equity_risk_state).values(
            {
                "account_id": state.account_id,
                "currency": state.currency,
                "day": state.day,
                "daily_equity_baseline": str(state.daily_equity_baseline),
                "peak_equity": str(state.peak_equity),
                "updated_at": state.updated_at,
            }
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["account_id", "currency"],
            set_={
                "day": stmt.excluded.day,
                "daily_equity_baseline": stmt.excluded.daily_equity_baseline,
                "peak_equity": stmt.excluded.peak_equity,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)
        return state

    def get_equity_risk_state(self, *, account_id: str, currency: str) -> EquityRiskState | None:
        stmt = (
            select(self.equity_risk_state)
            .where(self.equity_risk_state.c.account_id == account_id)
            .where(self.equity_risk_state.c.currency == currency)
        )
        with self.engine.begin() as conn:
            row = conn.execute(stmt).mappings().first()
        if row is None:
            return None
        return EquityRiskState(
            account_id=row["account_id"],
            currency=row["currency"],
            day=row["day"],
            daily_equity_baseline=Decimal(row["daily_equity_baseline"]),
            peak_equity=Decimal(row["peak_equity"]),
            updated_at=_ensure_utc(row["updated_at"]),
        )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
