from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def decimal_from_db(value) -> Decimal:
    rounded = Decimal(str(value)).quantize(Decimal("0.000000000001"))
    return rounded.quantize(Decimal("0.000000000000000001"))


def upsert_rows(conn, table: Table, rows: list[dict], keys: list[str]) -> None:
    if not rows:
        return
    stmt = sqlite_insert(table).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=keys,
        set_={column.name: getattr(stmt.excluded, column.name) for column in table.columns if column.name not in keys},
    )
    conn.execute(stmt)
