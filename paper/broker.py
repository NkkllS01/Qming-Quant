from __future__ import annotations

from decimal import Decimal

from simulation.broker import SimulationBroker


class PaperBroker(SimulationBroker):
    def __init__(self, initial_equity: Decimal) -> None:
        super().__init__(initial_equity, fill_id_prefix="paper")
