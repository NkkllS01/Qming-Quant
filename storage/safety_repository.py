from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, create_engine, select
from sqlalchemy.engine import Engine

from storage.db import ensure_utc, upsert_rows


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
        row = {
            "account_id": state.account_id,
            "paused": state.paused,
            "reason": state.reason,
            "updated_at": state.updated_at,
        }
        with self.engine.begin() as conn:
            upsert_rows(conn, self.pause_state, [row], ["account_id"])
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
            updated_at=ensure_utc(row["updated_at"]),
        )

    def upsert_equity_risk_state(self, state: EquityRiskState) -> EquityRiskState:
        row = {
            "account_id": state.account_id,
            "currency": state.currency,
            "day": state.day,
            "daily_equity_baseline": str(state.daily_equity_baseline),
            "peak_equity": str(state.peak_equity),
            "updated_at": state.updated_at,
        }
        with self.engine.begin() as conn:
            upsert_rows(conn, self.equity_risk_state, [row], ["account_id", "currency"])
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
            updated_at=ensure_utc(row["updated_at"]),
        )
