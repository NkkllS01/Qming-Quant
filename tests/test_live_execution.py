from datetime import datetime, timezone
from decimal import Decimal

from core.models import OrderIntent
from live.execution import LiveOrderExecutionService
from live.trading_gate import TradingGateResult
from storage.live_repository import LiveStateRepository
from storage.safety_repository import PauseState


def test_live_order_execution_blocks_when_trading_gate_blocks() -> None:
    gateway = FakeGateway()
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=FakeTradingGate(status="blocked"),
    )

    result = service.submit_order(_intent())

    assert result.status == "blocked"
    assert result.submitted is False
    assert gateway.placed == []


def test_live_order_execution_places_order_when_gate_allows() -> None:
    gateway = FakeGateway()
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=FakeTradingGate(status="allowed"),
        td_mode="isolated",
    )

    result = service.submit_order(_intent())

    assert result.status == "submitted"
    assert result.submitted is True
    assert result.exchange_response == {"data": [{"ordId": "okx-1"}]}
    assert gateway.placed == [{"intent": _intent(), "td_mode": "isolated"}]


def test_live_order_execution_records_submitted_order_snapshot() -> None:
    gateway = FakeGateway()
    repository = LiveStateRepository("sqlite:///:memory:")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=FakeTradingGate(status="allowed"),
        live_state_repository=repository,
    )

    result = service.submit_order(_intent())

    assert result.submitted is True
    store = repository.load_snapshot(account_id="okx_sub_main")
    order = store.orders["okx-1"]
    assert order.account_id == "okx_sub_main"
    assert order.bot_id == "okx_perp_bot_main"
    assert order.strategy_id == "btc_trend_15m"
    assert order.symbol == "BTC-USDT-SWAP"
    assert order.run_id == "live"
    assert order.client_order_id == "client-1"
    assert order.status == "submitted"
    assert order.okx_order_id == "okx-1"


def test_live_order_execution_does_not_record_exchange_rejection() -> None:
    gateway = FakeGateway(response={"data": [{"ordId": "", "sCode": "51000", "sMsg": "rejected"}]})
    repository = LiveStateRepository("sqlite:///:memory:")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=FakeTradingGate(status="allowed"),
        live_state_repository=repository,
    )

    result = service.submit_order(_intent())

    assert result.status == "exchange_rejected"
    assert result.submitted is False
    assert repository.load_snapshot(account_id="okx_sub_main").orders == {}


def test_live_order_execution_cancel_updates_local_order_without_trading_gate() -> None:
    gateway = FakeGateway(cancel_response={"data": [{"ordId": "okx-1", "clOrdId": "client-1"}]})
    repository = LiveStateRepository("sqlite:///:memory:")
    trading_gate = FakeTradingGate(status="blocked")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
        live_state_repository=repository,
    )
    _seed_submitted_order(service)

    result = service.cancel_order(
        account_id="okx_sub_main",
        symbol="BTC-USDT-SWAP",
        order_id="okx-1",
    )

    assert result.status == "cancel_requested"
    assert result.accepted is True
    assert gateway.canceled == [
        {"symbol": "BTC-USDT-SWAP", "order_id": "okx-1", "client_order_id": None}
    ]
    assert trading_gate.evaluations == 0
    order = repository.load_snapshot(account_id="okx_sub_main").orders["okx-1"]
    assert order.status == "cancel_requested"


def test_live_order_execution_cancel_matches_local_order_by_client_order_id() -> None:
    gateway = FakeGateway(cancel_response={"data": [{"clOrdId": "client-1"}]})
    repository = LiveStateRepository("sqlite:///:memory:")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=FakeTradingGate(status="allowed"),
        live_state_repository=repository,
    )
    _seed_submitted_order(service)

    result = service.cancel_order(
        account_id="okx_sub_main",
        symbol="BTC-USDT-SWAP",
        client_order_id="client-1",
    )

    assert result.status == "cancel_requested"
    assert result.client_order_id == "client-1"
    assert repository.load_snapshot(account_id="okx_sub_main").orders["okx-1"].status == "cancel_requested"


def test_live_order_execution_cancel_rejection_does_not_update_local_order() -> None:
    gateway = FakeGateway(cancel_response={"data": [{"ordId": "okx-1", "sCode": "51400"}]})
    repository = LiveStateRepository("sqlite:///:memory:")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=FakeTradingGate(status="allowed"),
        live_state_repository=repository,
    )
    _seed_submitted_order(service)

    result = service.cancel_order(
        account_id="okx_sub_main",
        symbol="BTC-USDT-SWAP",
        order_id="okx-1",
    )

    assert result.status == "cancel_rejected"
    assert result.accepted is False
    assert repository.load_snapshot(account_id="okx_sub_main").orders["okx-1"].status == "submitted"


def test_live_order_execution_cancel_does_not_update_different_symbol_order() -> None:
    gateway = FakeGateway(cancel_response={"data": [{"ordId": "okx-1"}]})
    repository = LiveStateRepository("sqlite:///:memory:")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=FakeTradingGate(status="allowed"),
        live_state_repository=repository,
    )
    _seed_submitted_order(service)

    result = service.cancel_order(
        account_id="okx_sub_main",
        symbol="ETH-USDT-SWAP",
        order_id="okx-1",
    )

    assert result.status == "cancel_requested"
    assert repository.load_snapshot(account_id="okx_sub_main").orders["okx-1"].status == "submitted"


def test_live_order_execution_cancel_requires_order_identifier() -> None:
    service = LiveOrderExecutionService(
        gateway=FakeGateway(),
        trading_gate=FakeTradingGate(status="allowed"),
    )

    try:
        service.cancel_order(account_id="okx_sub_main", symbol="BTC-USDT-SWAP")
    except ValueError as exc:
        assert "requires order_id" in str(exc)
    else:
        raise AssertionError("expected cancel_order to require an order identifier")


class FakeGateway:
    def __init__(self, response: dict | None = None, cancel_response: dict | None = None) -> None:
        self.placed: list[dict] = []
        self.canceled: list[dict] = []
        self.response = response or {"data": [{"ordId": "okx-1"}]}
        self.cancel_response = cancel_response or {"data": [{"ordId": "okx-1"}]}

    def place_order(self, intent: OrderIntent, *, td_mode: str) -> dict:
        self.placed.append({"intent": intent, "td_mode": td_mode})
        return self.response

    def cancel_order(
        self,
        *,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        self.canceled.append(
            {"symbol": symbol, "order_id": order_id, "client_order_id": client_order_id}
        )
        return self.cancel_response


class FakeTradingGate:
    def __init__(self, *, status: str) -> None:
        self.status = status
        self.evaluations = 0

    def evaluate(self) -> TradingGateResult:
        self.evaluations += 1
        return TradingGateResult(
            status=self.status,
            reason="test",
            pause_state=PauseState(
                account_id="okx_sub_main",
                paused=self.status != "allowed",
                reason="test",
                updated_at=datetime.now(timezone.utc),
            ),
        )


def _intent() -> OrderIntent:
    return OrderIntent(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="live",
        side="buy",
        position_action="open",
        order_type="market",
        size=Decimal("0.1"),
        price=None,
        reduce_only=False,
        client_order_id="client-1",
    )


def _seed_submitted_order(service: LiveOrderExecutionService) -> None:
    service._record_submitted_order(_intent(), {"data": [{"ordId": "okx-1"}]})
