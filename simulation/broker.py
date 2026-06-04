from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from core.models import Fill, OrderIntent, Position


class SimulationBroker:
    def __init__(self, initial_equity: Decimal, *, fill_id_prefix: str = "sim") -> None:
        self.equity = initial_equity
        self.fill_id_prefix = fill_id_prefix
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []

    def execute(self, intent: OrderIntent, *, market_price: Decimal) -> Fill:
        fill = Fill(
            account_id=intent.account_id,
            bot_id=intent.bot_id,
            strategy_id=intent.strategy_id,
            symbol=intent.symbol,
            run_id=intent.run_id,
            fill_id=f"{self.fill_id_prefix}-{len(self.fills) + 1}",
            client_order_id=intent.client_order_id,
            side=intent.side,
            size=intent.size,
            price=market_price,
        )
        self.fills.append(fill)
        if intent.position_action == "open":
            self._open_position(intent, market_price)
        elif intent.position_action in {"close", "reduce"}:
            self._close_position(intent.symbol, market_price)
        return fill

    def _open_position(self, intent: OrderIntent, market_price: Decimal) -> None:
        direction = "long" if intent.side == "buy" else "short"
        self.positions[intent.symbol] = Position(
            account_id=intent.account_id,
            symbol=intent.symbol,
            direction=direction,
            size=intent.size,
            entry_price=market_price,
            mark_price=market_price,
        )

    def _close_position(self, symbol: str, market_price: Decimal) -> None:
        position = self.positions.get(symbol)
        if position is not None:
            self.equity = (self.equity + _position_pnl(position, market_price)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        self.positions.pop(symbol, None)


def _position_pnl(position: Position, market_price: Decimal) -> Decimal:
    if position.direction == "long":
        return (market_price - position.entry_price) * position.size
    return (position.entry_price - market_price) * position.size
