from __future__ import annotations


class SymbolLeaseManager:
    def __init__(self) -> None:
        self._leases: dict[str, str] = {}

    def acquire(self, symbol: str, strategy_id: str) -> None:
        owner = self._leases.get(symbol)
        if owner and owner != strategy_id:
            raise ValueError(f"{symbol} is already leased by {owner}")
        self._leases[symbol] = strategy_id

    def can_open(self, symbol: str, strategy_id: str) -> bool:
        owner = self._leases.get(symbol)
        return owner is None or owner == strategy_id

