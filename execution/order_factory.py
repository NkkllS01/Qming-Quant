from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from core.models import OrderIntent, Signal


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


class OrderFactory:
    def __init__(self) -> None:
        self._sequence = 0

    def from_signal(
        self,
        signal: Signal,
        *,
        size: Decimal,
        price: Decimal | None,
        tick_size: Decimal,
        lot_size: Decimal,
        min_size: Decimal,
    ) -> OrderIntent:
        side = "buy" if signal.direction == "long" else "sell"
        symbol_short = signal.symbol.split("-")[0]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self._sequence += 1
        client_order_id = (
            f"{signal.bot_id}-{signal.strategy_id}-{symbol_short}-{timestamp}-{self._sequence:06d}"
        )
        quantized_size = _floor_to_step(size, lot_size)
        if quantized_size < min_size:
            raise ValueError(
                f"order size {quantized_size} is below minimum order size {min_size} for {signal.symbol}"
            )
        return OrderIntent(
            account_id=signal.account_id,
            bot_id=signal.bot_id,
            strategy_id=signal.strategy_id,
            symbol=signal.symbol,
            run_id=signal.run_id,
            side=side,
            position_action=signal.action,
            order_type="market" if price is None else "limit",
            size=quantized_size,
            price=_floor_to_step(price, tick_size) if price is not None else None,
            reduce_only=signal.action in {"close", "reduce"},
            client_order_id=client_order_id,
        )
