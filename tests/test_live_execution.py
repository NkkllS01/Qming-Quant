from datetime import datetime, timezone
from decimal import Decimal

from core.models import Instrument, OrderIntent
from live.execution import LiveOrderExecutionService
from live.trading_gate import TradingGateResult
from storage.live_repository import LiveStateRepository
from storage.repositories import InstrumentRepository
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


def test_live_order_execution_rejects_symbol_outside_policy_before_gate() -> None:
    gateway = FakeGateway()
    trading_gate = FakeTradingGate(status="allowed")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
    )

    result = service.submit_order(_intent(symbol="SOL-USDT-SWAP"))

    assert result.status == "policy_rejected"
    assert result.reason == "symbol_not_allowed"
    assert result.trading_gate is None
    assert trading_gate.evaluations == 0
    assert gateway.placed == []


def test_live_order_execution_rejects_close_without_reduce_only_before_gate() -> None:
    gateway = FakeGateway()
    trading_gate = FakeTradingGate(status="allowed")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
    )

    result = service.submit_order(_intent(position_action="close", reduce_only=False))

    assert result.status == "policy_rejected"
    assert result.reason == "close_order_requires_reduce_only"
    assert trading_gate.evaluations == 0
    assert gateway.placed == []


def test_live_order_execution_rejects_limit_orders_before_gate() -> None:
    gateway = FakeGateway()
    trading_gate = FakeTradingGate(status="allowed")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
    )

    result = service.submit_order(_intent(order_type="limit", price=Decimal("70000")))

    assert result.status == "policy_rejected"
    assert result.reason == "order_type_not_allowed"
    assert trading_gate.evaluations == 0
    assert gateway.placed == []


def test_live_order_execution_rejects_market_order_with_price_before_gate() -> None:
    gateway = FakeGateway()
    trading_gate = FakeTradingGate(status="allowed")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
    )

    result = service.submit_order(_intent(price=Decimal("70000")))

    assert result.status == "policy_rejected"
    assert result.reason == "market_order_must_not_have_price"
    assert trading_gate.evaluations == 0
    assert gateway.placed == []


def test_live_order_execution_rejects_missing_instrument_spec_before_gate() -> None:
    gateway = FakeGateway()
    trading_gate = FakeTradingGate(status="allowed")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
        instrument_repository=InstrumentRepository("sqlite:///:memory:"),
    )

    result = service.submit_order(_intent())

    assert result.status == "policy_rejected"
    assert result.reason == "instrument_spec_missing"
    assert trading_gate.evaluations == 0
    assert gateway.placed == []


def test_live_order_execution_rejects_size_below_instrument_minimum_before_gate() -> None:
    gateway = FakeGateway()
    trading_gate = FakeTradingGate(status="allowed")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    _seed_instrument(instrument_repo, min_size=Decimal("0.1"), lot_size=Decimal("0.01"))
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
        instrument_repository=instrument_repo,
    )

    result = service.submit_order(_intent(size=Decimal("0.01")))

    assert result.status == "policy_rejected"
    assert result.reason == "size_below_min_size"
    assert trading_gate.evaluations == 0
    assert gateway.placed == []


def test_live_order_execution_rejects_size_not_matching_lot_size_before_gate() -> None:
    gateway = FakeGateway()
    trading_gate = FakeTradingGate(status="allowed")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    _seed_instrument(instrument_repo, min_size=Decimal("0.01"), lot_size=Decimal("0.01"))
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
        instrument_repository=instrument_repo,
    )

    result = service.submit_order(_intent(size=Decimal("0.015")))

    assert result.status == "policy_rejected"
    assert result.reason == "size_not_multiple_of_lot_size"
    assert trading_gate.evaluations == 0
    assert gateway.placed == []


def test_live_order_execution_accepts_size_matching_local_instrument_spec() -> None:
    gateway = FakeGateway()
    trading_gate = FakeTradingGate(status="allowed")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    _seed_instrument(instrument_repo, min_size=Decimal("0.01"), lot_size=Decimal("0.01"))
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
        instrument_repository=instrument_repo,
    )

    result = service.submit_order(_intent(size=Decimal("0.1")))

    assert result.status == "submitted"
    assert trading_gate.evaluations == 1
    assert gateway.placed == [{"intent": _intent(size=Decimal("0.1")), "td_mode": "isolated"}]


def test_live_order_execution_check_order_allows_without_placing() -> None:
    gateway = FakeGateway()
    trading_gate = FakeTradingGate(status="allowed")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
    )

    result = service.check_order(_intent())

    assert result.status == "allowed"
    assert result.reason == "order_check_passed"
    assert result.policy.reason == "order_policy_passed"
    assert result.trading_gate is not None
    assert trading_gate.evaluations == 1
    assert gateway.placed == []


def test_live_order_execution_rejects_duplicate_active_client_order_id_before_gate() -> None:
    gateway = FakeGateway()
    trading_gate = FakeTradingGate(status="allowed")
    repository = LiveStateRepository("sqlite:///:memory:")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
        live_state_repository=repository,
    )
    _seed_submitted_order(service)

    result = service.submit_order(_intent())

    assert result.status == "local_state_rejected"
    assert result.reason == "duplicate_client_order_id"
    assert trading_gate.evaluations == 0
    assert gateway.placed == []


def test_live_order_execution_allows_reusing_client_order_id_after_terminal_order() -> None:
    gateway = FakeGateway()
    trading_gate = FakeTradingGate(status="allowed")
    repository = LiveStateRepository("sqlite:///:memory:")
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=trading_gate,
        live_state_repository=repository,
    )
    _seed_submitted_order(service)
    store = repository.load_snapshot(account_id="okx_sub_main")
    existing = store.orders["okx-1"]
    store.upsert_order(existing.model_copy(update={"status": "filled"}))
    repository.save_snapshot(account_id="okx_sub_main", store=store)

    result = service.check_order(_intent())

    assert result.status == "allowed"
    assert result.reason == "order_check_passed"
    assert trading_gate.evaluations == 1


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


def test_live_order_execution_allows_reduce_only_close_order() -> None:
    gateway = FakeGateway()
    service = LiveOrderExecutionService(
        gateway=gateway,
        trading_gate=FakeTradingGate(status="allowed"),
    )
    intent = _intent(position_action="close", side="sell", reduce_only=True)

    result = service.submit_order(intent)

    assert result.status == "submitted"
    assert gateway.placed == [{"intent": intent, "td_mode": "isolated"}]


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


def _intent(
    *,
    symbol: str = "BTC-USDT-SWAP",
    side: str = "buy",
    position_action: str = "open",
    order_type: str = "market",
    size: Decimal = Decimal("0.1"),
    price: Decimal | None = None,
    reduce_only: bool = False,
) -> OrderIntent:
    return OrderIntent(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol=symbol,
        run_id="live",
        side=side,
        position_action=position_action,
        order_type=order_type,
        size=size,
        price=price,
        reduce_only=reduce_only,
        client_order_id="client-1",
    )


def _seed_submitted_order(service: LiveOrderExecutionService) -> None:
    service._record_submitted_order(_intent(), {"data": [{"ordId": "okx-1"}]})


def _seed_instrument(
    repository: InstrumentRepository,
    *,
    min_size: Decimal,
    lot_size: Decimal,
    state: str = "live",
) -> None:
    repository.upsert_many(
        [
            Instrument(
                symbol="BTC-USDT-SWAP",
                inst_type="SWAP",
                tick_size=Decimal("0.1"),
                lot_size=lot_size,
                min_size=min_size,
                state=state,
            )
        ]
    )
