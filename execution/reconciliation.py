from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from core.models import Position


@dataclass(frozen=True)
class ReconciliationIssue:
    kind: str
    symbol: str
    local_value: Any
    exchange_value: Any
    message: str


@dataclass(frozen=True)
class ReconciliationReport:
    issues: list[ReconciliationIssue] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.issues


class Reconciliation:
    def compare_order_ids(self, local_ids: set[str], exchange_ids: set[str]) -> dict[str, set[str]]:
        return {
            "missing_on_exchange": local_ids - exchange_ids,
            "missing_locally": exchange_ids - local_ids,
        }

    def compare_positions(
        self,
        local_positions: list[Position],
        exchange_positions: list[dict[str, Any]],
    ) -> ReconciliationReport:
        issues: list[ReconciliationIssue] = []
        local_by_symbol: dict[str, Position] = {}
        duplicate_local_symbols: set[str] = set()
        for position in local_positions:
            if position.symbol in local_by_symbol:
                if position.symbol not in duplicate_local_symbols:
                    issues.append(
                        ReconciliationIssue(
                            kind="duplicate_local_position",
                            symbol=position.symbol,
                            local_value="duplicate",
                            exchange_value=None,
                            message=f"Local position {position.symbol} appears more than once.",
                        )
                    )
                duplicate_local_symbols.add(position.symbol)
                continue
            local_by_symbol[position.symbol] = position

        exchange_by_symbol: dict[str, tuple[dict[str, Any], Decimal, str]] = {}
        duplicate_exchange_symbols: set[str] = set()
        for position in exchange_positions:
            parsed_position = self._parse_exchange_position(position)
            if isinstance(parsed_position, ReconciliationIssue):
                issues.append(parsed_position)
                continue

            symbol, size, direction = parsed_position
            if symbol in exchange_by_symbol:
                if symbol not in duplicate_exchange_symbols:
                    issues.append(
                        ReconciliationIssue(
                            kind="duplicate_exchange_position",
                            symbol=symbol,
                            local_value=None,
                            exchange_value="duplicate",
                            message=f"Exchange position {symbol} appears more than once.",
                        )
                    )
                duplicate_exchange_symbols.add(symbol)
                continue
            exchange_by_symbol[symbol] = (position, size, direction)

        for symbol, local_position in local_by_symbol.items():
            if symbol in duplicate_local_symbols or symbol in duplicate_exchange_symbols:
                continue

            exchange_position = exchange_by_symbol.get(symbol)
            if exchange_position is None:
                issues.append(
                    ReconciliationIssue(
                        kind="missing_on_exchange",
                        symbol=symbol,
                        local_value="present",
                        exchange_value=None,
                        message=f"Local position {symbol} is missing on exchange snapshot.",
                    )
                )
                continue

            local_size = Decimal(local_position.size)
            _, exchange_size, exchange_direction = exchange_position
            if local_size != exchange_size:
                issues.append(
                    ReconciliationIssue(
                        kind="size_mismatch",
                        symbol=symbol,
                        local_value=local_size,
                        exchange_value=exchange_size,
                        message=f"Position size mismatch for {symbol}: local={local_size} exchange={exchange_size}.",
                    )
                )

            if local_position.direction != exchange_direction:
                issues.append(
                    ReconciliationIssue(
                        kind="direction_mismatch",
                        symbol=symbol,
                        local_value=local_position.direction,
                        exchange_value=exchange_direction,
                        message=(
                            f"Position direction mismatch for {symbol}: "
                            f"local={local_position.direction} exchange={exchange_direction}."
                        ),
                    )
                )

        for symbol in exchange_by_symbol:
            if symbol in duplicate_exchange_symbols:
                continue
            if symbol not in local_by_symbol and symbol not in duplicate_local_symbols:
                issues.append(
                    ReconciliationIssue(
                        kind="missing_locally",
                        symbol=symbol,
                        local_value=None,
                        exchange_value="present",
                        message=f"Exchange position {symbol} is missing locally.",
                    )
                )

        return ReconciliationReport(issues=issues)

    def _parse_exchange_position(self, position: dict[str, Any]) -> tuple[str, Decimal, str] | ReconciliationIssue:
        raw_symbol = position.get("symbol")
        if raw_symbol is None or str(raw_symbol).strip() == "":
            return ReconciliationIssue(
                kind="malformed_exchange_position",
                symbol="<unknown>",
                local_value=None,
                exchange_value=position,
                message="Exchange position row is malformed: missing symbol.",
            )

        symbol = str(raw_symbol)
        raw_direction = position.get("direction")
        if raw_direction is None or str(raw_direction).strip() == "":
            return ReconciliationIssue(
                kind="malformed_exchange_position",
                symbol=symbol,
                local_value=None,
                exchange_value=position,
                message=f"Exchange position {symbol} is malformed: missing direction.",
            )

        raw_size = position.get("size")
        if raw_size is None or str(raw_size).strip() == "":
            return ReconciliationIssue(
                kind="malformed_exchange_position",
                symbol=symbol,
                local_value=None,
                exchange_value=position,
                message=f"Exchange position {symbol} is malformed: missing size.",
            )

        try:
            size = Decimal(str(raw_size))
        except (InvalidOperation, ValueError):
            return ReconciliationIssue(
                kind="malformed_exchange_position",
                symbol=symbol,
                local_value=None,
                exchange_value=position,
                message=f"Exchange position {symbol} has malformed size.",
            )

        if not size.is_finite():
            return ReconciliationIssue(
                kind="malformed_exchange_position",
                symbol=symbol,
                local_value=None,
                exchange_value=position,
                message=f"Exchange position {symbol} has malformed size.",
            )

        return symbol, size, str(raw_direction)
