from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.main import AppServices, build_parser, run_command
from app.run_log import RuntimeEventLogger
from tests.test_live_strategy_dry_run import crossover_candles
from core.models import Instrument, MarkPrice
from storage.live_intent_repository import LiveIntentRepository
from storage.live_repository import LiveStateRepository
from storage.repositories import CandleRepository, InstrumentRepository, MarkPriceRepository
from storage.safety_repository import SafetyRepository
from tests.cli_fakes import FakeGateway, add_usdt_balance
from tests.fakes import live_store_with_position_and_order


def test_live_strategy_dry_run_cli_writes_intent_journal_and_summary() -> None:
    candle_repo = CandleRepository("sqlite:///:memory:")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    intent_repo = LiveIntentRepository("sqlite:///:memory:")
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}]
    gateway.rest_orders = [{"ordId": "okx-1"}]
    candle_repo.upsert_many(crossover_candles(datetime(2024, 1, 1, tzinfo=timezone.utc)))
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
                mark_price=Decimal("112"),
                updated_at=datetime.now(timezone.utc),
            )
        ]
    )
    store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    add_usdt_balance(store)
    live_repo.save_snapshot(account_id="okx_sub_main", store=store)
    services = AppServices(
        gateway=gateway,
        candle_repository=candle_repo,
        instrument_repository=instrument_repo,
        mark_price_repository=mark_repo,
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        live_intent_repository=intent_repo,
        runtime_logger=RuntimeEventLogger(Path(f"test-runtime-events-cli-dry-run-{uuid4().hex}.jsonl")),
    )
    args = build_parser().parse_args(
        [
            "live-strategy-dry-run",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "15m",
            "--strategy",
            "ma-crossover",
        ]
    )

    output = run_command(args, services)

    assert "live_strategy_dry_run symbol=BTC-USDT-SWAP timeframe=15m strategy=ma-crossover" in output
    assert "signals=1 intents=1 allowed=0 rejected=1" in output
    assert "last_status=risk_rejected" in output
    assert intent_repo.list_entries()[0].status == "risk_rejected"
