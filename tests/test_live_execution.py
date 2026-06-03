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


class FakeGateway:
    def __init__(self, response: dict | None = None) -> None:
        self.placed: list[dict] = []
        self.response = response or {"data": [{"ordId": "okx-1"}]}

    def place_order(self, intent: OrderIntent, *, td_mode: str) -> dict:
        self.placed.append({"intent": intent, "td_mode": td_mode})
        return self.response


class FakeTradingGate:
    def __init__(self, *, status: str) -> None:
        self.status = status

    def evaluate(self) -> TradingGateResult:
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
