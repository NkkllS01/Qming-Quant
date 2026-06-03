from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.models import OrderIntent
from live.trading_gate import TradingGateResult, TradingGateService


@dataclass(frozen=True)
class LiveOrderExecutionResult:
    status: str
    intent: OrderIntent
    trading_gate: TradingGateResult
    exchange_response: dict[str, Any] | None = None

    @property
    def submitted(self) -> bool:
        return self.status == "submitted"


class LiveOrderExecutionService:
    def __init__(
        self,
        *,
        gateway: object,
        trading_gate: TradingGateService,
        td_mode: str = "isolated",
    ) -> None:
        self.gateway = gateway
        self.trading_gate = trading_gate
        self.td_mode = td_mode

    def submit_order(self, intent: OrderIntent) -> LiveOrderExecutionResult:
        gate_result = self.trading_gate.evaluate()
        if not gate_result.trading_allowed:
            return LiveOrderExecutionResult(
                status="blocked",
                intent=intent,
                trading_gate=gate_result,
            )
        response = self.gateway.place_order(intent, td_mode=self.td_mode)
        return LiveOrderExecutionResult(
            status="submitted",
            intent=intent,
            trading_gate=gate_result,
            exchange_response=response,
        )
