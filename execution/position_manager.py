from __future__ import annotations

from core.models import Position


class PositionManager:
    def __init__(self) -> None:
        self.positions: dict[str, Position] = {}

    def set_position(self, position: Position) -> None:
        self.positions[position.symbol] = position

