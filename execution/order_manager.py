from __future__ import annotations

from core.models import OrderIntent


class OrderManager:
    def __init__(self) -> None:
        self.submitted: list[OrderIntent] = []

    def submit(self, intent: OrderIntent) -> OrderIntent:
        self.submitted.append(intent)
        return intent

