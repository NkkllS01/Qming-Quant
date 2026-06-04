from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.main import AppServices, build_parser, run_command
from app.run_log import RuntimeEventLogger
from core.models import Instrument, MarkPrice
from live.state import LiveStateStore
from storage.live_repository import LiveStateRepository
from storage.repositories import CandleRepository, InstrumentRepository, MarkPriceRepository
from storage.safety_repository import SafetyRepository
from tests.cli_fakes import FakeGateway, add_usdt_balance
from tests.fakes import live_store_with_position_and_order


class SimulatedExecutionGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.place_order_calls = 0
        self.cancel_order_calls = 0
        self.last_client_order_id = None

    def place_order(self, intent, *, td_mode: str) -> dict:
        self.place_order_calls += 1
        self.last_client_order_id = intent.client_order_id
        order_id = f"sim-okx-{self.place_order_calls}"
        self.rest_orders.append({"ordId": order_id, "clOrdId": intent.client_order_id})
        return {"code": "0", "data": [{"ordId": order_id, "clOrdId": intent.client_order_id, "sCode": "0"}]}

    def cancel_order(self, *, symbol: str, order_id: str | None = None, client_order_id: str | None = None) -> dict:
        self.cancel_order_calls += 1
        self.rest_orders = [
            row
            for row in self.rest_orders
            if row.get("ordId") != order_id and row.get("clOrdId") != client_order_id
        ]
        return {
            "code": "0",
            "data": [
                {
                    "ordId": order_id or "sim-okx-1",
                    "clOrdId": client_order_id or "",
                    "sCode": "0",
                }
            ],
        }


def test_live_simulated_execute_requires_explicit_enable_flag() -> None:
    services = AppServices(
        gateway=SimulatedExecutionGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        okx_simulated_trading=True,
    )
    args = build_parser().parse_args(
        [
            "live-simulated-execute",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.1",
        ]
    )

    try:
        run_command(args, services)
    except RuntimeError as exc:
        assert "--enable-simulated-execution is required" in str(exc)
    else:
        raise AssertionError("expected simulated execution to require an explicit enable flag")


def _ready_simulated_services(
    gateway: SimulatedExecutionGateway,
    *,
    store: LiveStateStore | None = None,
    database_url: str = "sqlite:///:memory:",
) -> tuple[AppServices, LiveStateRepository]:
    live_repo = LiveStateRepository(database_url)
    safety_repo = SafetyRepository("sqlite:///:memory:")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    live_store = store or live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    add_usdt_balance(live_store)
    live_repo.save_snapshot(account_id="okx_sub_main", store=live_store)
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
    gateway.rest_positions = [
        {
            "instId": position.symbol,
            "posSide": position.direction,
            "pos": str(position.size),
        }
        for position in live_store.positions.values()
    ]
    gateway.rest_orders = [
        {
            "ordId": order.order_id,
            "clOrdId": order.client_order_id,
        }
        for order in live_store.orders.values()
    ]
    return (
        AppServices(
            gateway=gateway,
            candle_repository=CandleRepository("sqlite:///:memory:"),
            instrument_repository=instrument_repo,
            mark_price_repository=mark_repo,
            live_state_repository=live_repo,
            safety_repository=safety_repo,
            runtime_logger=RuntimeEventLogger(Path(f"test-runtime-events-sim-exec-{uuid4().hex}.jsonl")),
            okx_simulated_trading=True,
        ),
        live_repo,
    )


def test_live_simulated_execute_submits_only_when_simulated_and_ready() -> None:
    gateway = SimulatedExecutionGateway()
    services, live_repo = _ready_simulated_services(gateway)
    args = build_parser().parse_args(
        [
            "live-simulated-execute",
            "--enable-simulated-execution",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.1",
            "--client-order-id",
            "sim-client-1",
        ]
    )

    output = run_command(args, services)

    assert "live_simulated_execute status=submitted" in output
    assert "reconcile_status=clean" in output
    assert gateway.place_order_calls == 1
    snapshot = live_repo.load_snapshot(account_id="okx_sub_main")
    assert snapshot.orders["sim-okx-1"].client_order_id == "sim-client-1"


def test_live_simulated_execute_can_submit_close_reduce_only_order() -> None:
    gateway = SimulatedExecutionGateway()
    database_url = f"sqlite:///file:live_state_sim_exec_{uuid4().hex}?mode=memory&cache=shared&uri=true"
    services, live_repo = _ready_simulated_services(gateway, database_url=database_url)
    args = build_parser().parse_args(
        [
            "live-simulated-execute",
            "--enable-simulated-execution",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "sell",
            "--position-action",
            "close",
            "--reduce-only",
            "--size",
            "0.1",
            "--client-order-id",
            "sim-close-1",
        ]
    )

    output = run_command(args, services)

    assert "live_simulated_execute status=submitted" in output
    snapshot = live_repo.load_snapshot(account_id="okx_sub_main")
    assert snapshot.orders["sim-okx-1"].client_order_id == "sim-close-1"
    restarted_repo = LiveStateRepository(database_url)
    recovered = restarted_repo.load_snapshot(account_id="okx_sub_main")
    assert recovered.orders["sim-okx-1"].client_order_id == "sim-close-1"


def test_live_simulated_cancel_requires_enable_flag_and_records_cancel_requested() -> None:
    gateway = SimulatedExecutionGateway()
    services, live_repo = _ready_simulated_services(gateway)
    disabled_args = build_parser().parse_args(
        [
            "live-simulated-cancel",
            "--symbol",
            "BTC-USDT-SWAP",
            "--order-id",
            "okx-1",
        ]
    )
    try:
        run_command(disabled_args, services)
    except RuntimeError as exc:
        assert "--enable-simulated-execution is required" in str(exc)
    else:
        raise AssertionError("expected simulated cancel to require explicit enable flag")

    args = build_parser().parse_args(
        [
            "live-simulated-cancel",
            "--enable-simulated-execution",
            "--symbol",
            "BTC-USDT-SWAP",
            "--order-id",
            "okx-1",
        ]
    )

    output = run_command(args, services)

    assert "live_simulated_cancel status=cancel_requested" in output
    assert gateway.cancel_order_calls == 1
    snapshot = live_repo.load_snapshot(account_id="okx_sub_main")
    assert snapshot.orders["okx-1"].status == "cancel_requested"
