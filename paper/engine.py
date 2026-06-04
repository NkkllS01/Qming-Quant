from __future__ import annotations

from decimal import Decimal

from simulation.engine import SimulationExitPlan, SimulationTradingEngine


PaperExitPlan = SimulationExitPlan


class PaperTradingEngine(SimulationTradingEngine):
    def __init__(
        self,
        *,
        initial_equity: Decimal,
        default_size: Decimal = Decimal("0.1"),
        max_risk_per_trade: Decimal = Decimal("0.005"),
        max_daily_loss: Decimal = Decimal("0.03"),
        max_total_drawdown_pause: Decimal = Decimal("0.08"),
        max_open_positions: int = 2,
        current_daily_loss: Decimal = Decimal("0"),
        current_drawdown: Decimal = Decimal("0"),
        tick_size: Decimal = Decimal("0.1"),
        lot_size: Decimal = Decimal("0.01"),
        min_size: Decimal = Decimal("0.01"),
    ) -> None:
        super().__init__(
            initial_equity=initial_equity,
            default_size=default_size,
            max_risk_per_trade=max_risk_per_trade,
            max_daily_loss=max_daily_loss,
            max_total_drawdown_pause=max_total_drawdown_pause,
            max_open_positions=max_open_positions,
            current_daily_loss=current_daily_loss,
            current_drawdown=current_drawdown,
            tick_size=tick_size,
            lot_size=lot_size,
            min_size=min_size,
            fill_id_prefix="paper",
        )
