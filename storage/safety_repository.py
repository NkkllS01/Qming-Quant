from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, create_engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class PauseState:
    account_id: str
    paused: bool
    reason: str
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


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
