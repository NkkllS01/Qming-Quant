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
    trading_gate: TradingGateResult | None
    exchange_response: dict[str, Any] | None = None
    reason: str = ""

    @property
    def submitted(self) -> bool:
        return self.status == "submitted"


@dataclass(frozen=True)
class LiveOrderPolicyResult:
    approved: bool
    reason: str


@dataclass(frozen=True)
class LiveOrderPolicy:
    allowed_symbols: tuple[str, ...] = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
    allowed_td_modes: tuple[str, ...] = ("isolated",)
    allowed_order_types: tuple[str, ...] = ("market",)
    allowed_position_actions: tuple[str, ...] = ("open", "close", "reduce")

    def evaluate(self, intent: OrderIntent, *, td_mode: str) -> LiveOrderPolicyResult:
        if intent.symbol not in self.allowed_symbols:
            return LiveOrderPolicyResult(False, "symbol_not_allowed")
        if td_mode not in self.allowed_td_modes:
            return LiveOrderPolicyResult(False, "td_mode_not_allowed")
        if intent.order_type not in self.allowed_order_types:
            return LiveOrderPolicyResult(False, "order_type_not_allowed")
        if intent.order_type == "market" and intent.price is not None:
            return LiveOrderPolicyResult(False, "market_order_must_not_have_price")
        if intent.position_action not in self.allowed_position_actions:
            return LiveOrderPolicyResult(False, "position_action_not_allowed")
        if intent.size <= 0:
            return LiveOrderPolicyResult(False, "size_must_be_positive")
        if intent.position_action == "open" and intent.reduce_only:
            return LiveOrderPolicyResult(False, "open_order_must_not_be_reduce_only")
        if intent.position_action in {"close", "reduce"} and not intent.reduce_only:
            return LiveOrderPolicyResult(False, "close_order_requires_reduce_only")
        return LiveOrderPolicyResult(True, "order_policy_passed")


@dataclass(frozen=True)
class LiveOrderCheckResult:
    status: str
    reason: str
    intent: OrderIntent
    policy: LiveOrderPolicyResult
    trading_gate: TradingGateResult | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "allowed"


@dataclass(frozen=True)
class LiveOrderCancellationResult:
    status: str
    account_id: str
    symbol: str
    order_id: str | None = None
    client_order_id: str | None = None
    exchange_response: dict[str, Any] | None = None

    @property
    def accepted(self) -> bool:
        return self.status == "cancel_requested"


class LiveOrderExecutionService:
    def __init__(
        self,
        *,
        gateway: object,
        trading_gate: TradingGateService,
        live_state_repository: LiveStateRepository | None = None,
        order_policy: LiveOrderPolicy | None = None,
        td_mode: str = "isolated",
    ) -> None:
        self.gateway = gateway
        self.trading_gate = trading_gate
        self.live_state_repository = live_state_repository
        self.order_policy = order_policy or LiveOrderPolicy()
        self.td_mode = td_mode

    def check_order(self, intent: OrderIntent) -> LiveOrderCheckResult:
        policy_result = self.order_policy.evaluate(intent, td_mode=self.td_mode)
        if not policy_result.approved:
            return LiveOrderCheckResult(
                status="policy_rejected",
                reason=policy_result.reason,
                intent=intent,
                policy=policy_result,
                trading_gate=None,
            )
        gate_result = self.trading_gate.evaluate()
        if not gate_result.trading_allowed:
            return LiveOrderCheckResult(
                status="blocked",
                reason=gate_result.reason,
                intent=intent,
                policy=policy_result,
                trading_gate=gate_result,
            )
        return LiveOrderCheckResult(
            status="allowed",
            reason="order_check_passed",
            intent=intent,
            policy=policy_result,
            trading_gate=gate_result,
        )

    def submit_order(self, intent: OrderIntent) -> LiveOrderExecutionResult:
        check_result = self.check_order(intent)
        if not check_result.allowed:
            return LiveOrderExecutionResult(
                status=check_result.status,
                intent=intent,
                trading_gate=check_result.trading_gate,
                reason=check_result.reason,
            )
        gate_result = check_result.trading_gate
        if gate_result is None:
            raise RuntimeError("live order check passed without a trading gate result")
        response = self.gateway.place_order(intent, td_mode=self.td_mode)
        if _is_exchange_rejection(response):
            return LiveOrderExecutionResult(
                status="exchange_rejected",
                intent=intent,
                trading_gate=gate_result,
                exchange_response=response,
                reason="exchange_rejected",
            )
        self._record_submitted_order(intent, response)
        return LiveOrderExecutionResult(
            status="submitted",
            intent=intent,
            trading_gate=gate_result,
            exchange_response=response,
            reason="submitted",
        )

    def cancel_order(
        self,
        *,
        account_id: str,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> LiveOrderCancellationResult:
        if order_id is None and client_order_id is None:
            raise ValueError("cancel_order requires order_id or client_order_id")
        response = self.gateway.cancel_order(
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
        )
        if _is_exchange_rejection(response):
            return LiveOrderCancellationResult(
                status="cancel_rejected",
                account_id=account_id,
                symbol=symbol,
                order_id=order_id,
                client_order_id=client_order_id,
                exchange_response=response,
            )
        exchange_order_id = _exchange_order_id(response) or order_id
        exchange_client_order_id = _exchange_client_order_id(response) or client_order_id
        self._record_cancel_requested(
            account_id=account_id,
            symbol=symbol,
            order_id=exchange_order_id,
            client_order_id=exchange_client_order_id,
        )
        return LiveOrderCancellationResult(
            status="cancel_requested",
            account_id=account_id,
            symbol=symbol,
            order_id=exchange_order_id,
            client_order_id=exchange_client_order_id,
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

    def _record_cancel_requested(
        self,
        *,
        account_id: str,
        symbol: str,
        order_id: str | None,
        client_order_id: str | None,
    ) -> None:
        if self.live_state_repository is None:
            return
        store = self.live_state_repository.load_snapshot(account_id=account_id)
        match_key = order_id or client_order_id
        if match_key is None:
            return
        existing = store.orders.get(match_key)
        if existing is None and client_order_id is not None:
            existing = next(
                (order for order in store.orders.values() if order.client_order_id == client_order_id),
                None,
            )
        if existing is None:
            return
        if existing.symbol != symbol:
            return
        updated = existing.model_copy(
            update={
                "status": "cancel_requested",
                "updated_at": datetime.now(timezone.utc),
            }
        )
        store.upsert_order(updated)
        self.live_state_repository.save_snapshot(account_id=account_id, store=store)


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


def _exchange_client_order_id(response: dict[str, Any]) -> str | None:
    value = _first_order_response(response).get("clOrdId")
    if value in {None, ""}:
        return None
    return str(value)


def _is_exchange_rejection(response: dict[str, Any]) -> bool:
    row = _first_order_response(response)
    status_code = row.get("sCode")
    return status_code not in {None, "", "0", 0}
