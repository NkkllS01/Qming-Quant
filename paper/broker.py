from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from core.models import Fill, OrderIntent, Position


class PaperBroker:
    def __init__(self, initial_equity: Decimal) -> None:
        self.equity = initial_equity
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []

    def execute(self, intent: OrderIntent, *, market_price: Decimal) -> Fill:
        fill = Fill(
            account_id=intent.account_id,
            bot_id=intent.bot_id,
            strategy_id=intent.strategy_id,
            symbol=intent.symbol,
            run_id=intent.run_id,
            fill_id=f"paper-{len(self.fills) + 1}",
            client_order_id=intent.client_order_id,
            side=intent.side,
            size=intent.size,
            price=market_price,
        )
        self.fills.append(fill)
        if intent.position_action == "open":
            direction = "long" if intent.side == "buy" else "short"
            self.positions[intent.symbol] = Position(
                account_id=intent.account_id,
                symbol=intent.symbol,
                direction=direction,
                size=intent.size,
                entry_price=market_price,
                mark_price=market_price,
            )
        elif intent.position_action in {"close", "reduce"}:
            position = self.positions.get(intent.symbol)
            if position is not None:
                if position.direction == "long":
                    pnl = (market_price - position.entry_price) * position.size
                else:
                    pnl = (position.entry_price - market_price) * position.size
                self.equity = (self.equity + pnl).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            self.positions.pop(intent.symbol, None)
        return fill
