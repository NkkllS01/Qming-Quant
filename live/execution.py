from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.models import Order, OrderIntent
from live.trading_gate import TradingGateResult, TradingGateService
from storage.live_repository import LiveStateRepository


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
        live_state_repository: LiveStateRepository | None = None,
        td_mode: str = "isolated",
    ) -> None:
        self.gateway = gateway
        self.trading_gate = trading_gate
        self.live_state_repository = live_state_repository
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
        if _is_exchange_rejection(response):
            return LiveOrderExecutionResult(
                status="exchange_rejected",
                intent=intent,
                trading_gate=gate_result,
                exchange_response=response,
            )
        self._record_submitted_order(intent, response)
        return LiveOrderExecutionResult(
            status="submitted",
            intent=intent,
            trading_gate=gate_result,
            exchange_response=response,
        )

    def _record_submitted_order(self, intent: OrderIntent, response: dict[str, Any]) -> None:
        if self.live_state_repository is None:
            return
        now = datetime.now(timezone.utc)
        exchange_order_id = _exchange_order_id(response) or intent.client_order_id
        store = self.live_state_repository.load_snapshot(account_id=intent.account_id)
        store.upsert_order(
            Order(
                account_id=intent.account_id,
                bot_id=intent.bot_id,
                strategy_id=intent.strategy_id,
                symbol=intent.symbol,
                run_id=intent.run_id,
                order_id=exchange_order_id,
                client_order_id=intent.client_order_id,
                side=intent.side,
                order_type=intent.order_type,
                size=intent.size,
                price=intent.price,
                status="submitted",
                okx_order_id=exchange_order_id,
                created_at=now,
                updated_at=now,
            )
        )
        self.live_state_repository.save_snapshot(account_id=intent.account_id, store=store)


def _first_order_response(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


def _exchange_order_id(response: dict[str, Any]) -> str | None:
    value = _first_order_response(response).get("ordId")
    if value in {None, ""}:
        return None
    return str(value)


def _is_exchange_rejection(response: dict[str, Any]) -> bool:
    row = _first_order_response(response)
    status_code = row.get("sCode")
    return status_code not in {None, "", "0", 0}
