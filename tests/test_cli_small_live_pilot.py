from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.main import AppServices, build_parser, run_command
from app.run_log import RuntimeEventLogger
from core.models import Instrument, MarkPrice, Order, Position
from live.state import AccountBalance, LiveStateStore
from storage.live_repository import LiveStateRepository
from storage.repositories import CandleRepository, InstrumentRepository, MarkPriceRepository
from storage.safety_repository import SafetyRepository
from tests.cli_fakes import FakeGateway


class SmallLiveGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.place_order_calls = 0

    def place_order(self, intent, *, td_mode: str) -> dict:
        self.place_order_calls += 1
        self.rest_orders.append({"ordId": "live-okx-1", "clOrdId": intent.client_order_id})
        return {"code": "0", "data": [{"ordId": "live-okx-1", "clOrdId": intent.client_order_id, "sCode": "0"}]}


def _ready_services(gateway: SmallLiveGateway) -> tuple[AppServices, LiveStateRepository]:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    store = LiveStateStore()
    store.upsert_balance(
        AccountBalance(
            currency="USDT",
            equity=Decimal("1000"),
            available=Decimal("900"),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
    )
    live_repo.save_snapshot(account_id="okx_sub_main", store=store)
    instrument_repo.upsert_many(
        [
            Instrument(
                symbol="BTC-USDT-SWAP",
                inst_type="SWAP",
                tick_size=Decimal("0.1"),
                lot_size=Decimal("0.01"),
                min_size=Decimal("0.01"),
                state="live",
            )
        ]
    )
    mark_repo.upsert_many(
        [
            MarkPrice(
                symbol="BTC-USDT-SWAP",
                mark_price=Decimal("70000"),
                updated_at=datetime.now(timezone.utc),
            )
        ]
    )
    gateway.rest_positions = []
    gateway.rest_orders = []
    return (
        AppServices(
            gateway=gateway,
            candle_repository=CandleRepository("sqlite:///:memory:"),
            instrument_repository=instrument_repo,
            mark_price_repository=mark_repo,
            live_state_repository=live_repo,
            safety_repository=safety_repo,
            runtime_logger=RuntimeEventLogger(Path(f"test-runtime-events-small-live-{uuid4().hex}.jsonl")),
            okx_simulated_trading=False,
        ),
        live_repo,
    )


def test_live_small_execute_requires_live_enable_flag_and_confirmation() -> None:
    services, _ = _ready_services(SmallLiveGateway())
    args = build_parser().parse_args(
        [
            "live-small-execute",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.01",
        ]
    )

    try:
        run_command(args, services)
    except RuntimeError as exc:
        assert "--enable-live-trading is required" in str(exc)
    else:
        raise AssertionError("expected small live execution to require live enable flag")

    args = build_parser().parse_args(
        [
            "live-small-execute",
            "--enable-live-trading",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.01",
        ]
    )
    try:
        run_command(args, services)
    except RuntimeError as exc:
        assert "--confirm-first-live-order is required" in str(exc)
    else:
        raise AssertionError("expected small live execution to require manual confirmation")


def test_live_small_execute_submits_tiny_confirmed_order_and_reconciles() -> None:
    gateway = SmallLiveGateway()
    services, live_repo = _ready_services(gateway)
    args = build_parser().parse_args(
        [
            "live-small-execute",
            "--enable-live-trading",
            "--confirm-first-live-order",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.01",
            "--client-order-id",
            "live-client-1",
        ]
    )

    output = run_command(args, services)

    assert "live_small_execute status=submitted" in output
    assert "reconcile_status=clean" in output
    assert gateway.place_order_calls == 1
    snapshot = live_repo.load_snapshot(account_id="okx_sub_main")
    assert snapshot.orders["live-okx-1"].client_order_id == "live-client-1"


def test_live_small_execute_rejects_size_above_live_pilot_limit() -> None:
    gateway = SmallLiveGateway()
    services, _ = _ready_services(gateway)
    args = build_parser().parse_args(
        [
            "live-small-execute",
            "--enable-live-trading",
            "--confirm-first-live-order",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.02",
            "--max-live-size",
            "0.01",
        ]
    )

    try:
        run_command(args, services)
    except RuntimeError as exc:
        assert "size exceeds max live pilot size" in str(exc)
    else:
        raise AssertionError("expected live pilot size limit to reject the order")

    assert gateway.place_order_calls == 0


def test_live_small_execute_rejects_when_local_active_order_limit_is_reached() -> None:
    gateway = SmallLiveGateway()
    services, live_repo = _ready_services(gateway)
    snapshot = live_repo.load_snapshot(account_id="okx_sub_main")
    now = datetime.now(timezone.utc)
    snapshot.upsert_order(
        Order(
            account_id="okx_sub_main",
            bot_id="existing",
            strategy_id="existing",
            symbol="BTC-USDT-SWAP",
            run_id="existing",
            order_id="existing-live-order",
            client_order_id="existing-live-order",
            side="buy",
            order_type="market",
            size=Decimal("0.01"),
            status="submitted",
            created_at=now,
            updated_at=now,
        )
    )
    live_repo.save_snapshot(account_id="okx_sub_main", store=snapshot)
    args = build_parser().parse_args(
        [
            "live-small-execute",
            "--enable-live-trading",
            "--confirm-first-live-order",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.01",
            "--max-live-orders",
            "1",
        ]
    )

    try:
        run_command(args, services)
    except RuntimeError as exc:
        assert "max live order count reached" in str(exc)
    else:
        raise AssertionError("expected active live order limit to reject the order")

    assert gateway.place_order_calls == 0


def test_live_small_execute_rejects_when_projected_position_exceeds_limit() -> None:
    gateway = SmallLiveGateway()
    services, live_repo = _ready_services(gateway)
    snapshot = live_repo.load_snapshot(account_id="okx_sub_main")
    snapshot.upsert_position(
        Position(
            account_id="okx_sub_main",
            symbol="BTC-USDT-SWAP",
            direction="long",
            size=Decimal("0.01"),
            entry_price=Decimal("70000"),
            mark_price=Decimal("70000"),
            updated_at=datetime.now(timezone.utc),
        )
    )
    live_repo.save_snapshot(account_id="okx_sub_main", store=snapshot)
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.01"}]
    args = build_parser().parse_args(
        [
            "live-small-execute",
            "--enable-live-trading",
            "--confirm-first-live-order",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.01",
            "--max-live-position-size",
            "0.01",
        ]
    )

    try:
        run_command(args, services)
    except RuntimeError as exc:
        assert "max live position size reached" in str(exc)
    else:
        raise AssertionError("expected live pilot position size limit to reject the order")

    assert gateway.place_order_calls == 0


def test_live_small_execute_rejects_when_single_order_risk_exceeds_limit() -> None:
    gateway = SmallLiveGateway()
    services, _ = _ready_services(gateway)
    args = build_parser().parse_args(
        [
            "live-small-execute",
            "--enable-live-trading",
            "--confirm-first-live-order",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.01",
            "--max-single-risk-usdt",
            "10",
        ]
    )

    try:
        run_command(args, services)
    except RuntimeError as exc:
        assert "max single live order risk reached" in str(exc)
    else:
        raise AssertionError("expected single-order risk limit to reject the order")

    assert gateway.place_order_calls == 0


def test_live_small_execute_is_blocked_by_emergency_pause() -> None:
    gateway = SmallLiveGateway()
    services, _ = _ready_services(gateway)
    assert services.safety_repository is not None
    services.safety_repository.set_pause(
        account_id="okx_sub_main",
        paused=True,
        reason="operator_stop",
    )
    args = build_parser().parse_args(
        [
            "live-small-execute",
            "--enable-live-trading",
            "--confirm-first-live-order",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.01",
        ]
    )

    try:
        run_command(args, services)
    except RuntimeError as exc:
        assert "prelive readiness blocked" in str(exc)
        assert "manual_pause" in str(exc)
    else:
        raise AssertionError("expected emergency pause to block small live execution")

    assert gateway.place_order_calls == 0
