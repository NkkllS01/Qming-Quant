from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.run_log import RuntimeEventLogger
from core.models import Candle, Instrument, MarkPrice
from live.state import LiveStateStore
from live.strategy_dry_run import LiveStrategyDryRunConfig, LiveStrategyDryRunService
from storage.live_intent_repository import LiveIntentRepository
from storage.live_repository import LiveStateRepository
from storage.repositories import CandleRepository, InstrumentRepository, MarkPriceRepository
from storage.safety_repository import SafetyRepository
from tests.cli_fakes import FakeGateway, add_usdt_balance
from tests.fakes import live_store_with_position_and_order


class NoOrderGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.place_order_calls = 0
        self.cancel_order_calls = 0

    def place_order(self, *args, **kwargs):
        self.place_order_calls += 1
        raise AssertionError("dry-run pipeline must not place orders")

    def cancel_order(self, *args, **kwargs):
        self.cancel_order_calls += 1
        raise AssertionError("dry-run pipeline must not cancel orders")


def crossover_candles(start: datetime) -> list[Candle]:
    closes = [Decimal("100") for _ in range(24)] + [Decimal("90") for _ in range(5)] + [Decimal("200")]
    return [
        Candle(
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            timestamp=start + index * (datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc) - start),
            open=close,
            high=close + Decimal("1"),
            low=close - Decimal("1"),
            close=close,
            volume=Decimal("100"),
            confirmed=True,
        )
        for index, close in enumerate(closes)
    ]


def test_live_strategy_dry_run_records_intent_journal_without_placing_orders() -> None:
    candle_repo = CandleRepository("sqlite:///:memory:")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    intent_repo = LiveIntentRepository("sqlite:///:memory:")
    gateway = NoOrderGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}]
    gateway.rest_orders = [{"ordId": "okx-1"}]
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candle_repo.upsert_many(crossover_candles(start))
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
    log_path = Path(f"test-runtime-events-live-dry-run-{uuid4().hex}.jsonl")

    result = LiveStrategyDryRunService(
        gateway=gateway,
        candle_repository=candle_repo,
        instrument_repository=instrument_repo,
        mark_price_repository=mark_repo,
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        intent_repository=intent_repo,
        runtime_logger=RuntimeEventLogger(log_path),
    ).run(
        LiveStrategyDryRunConfig(
            account_id="okx_sub_main",
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            strategy="ma-crossover",
        )
    )

    assert result.signals_count == 1
    assert result.intents_count == 1
    assert result.allowed_count == 0
    assert result.rejected_count == 1
    assert result.decisions[0].risk_reason == "symbol already open"
    assert result.decisions[0].status == "risk_rejected"
    assert gateway.place_order_calls == 0
    assert gateway.cancel_order_calls == 0
    entries = intent_repo.list_entries(run_id=result.run_id)
    assert len(entries) == 1
    assert entries[0].symbol == "BTC-USDT-SWAP"
    assert entries[0].status == "risk_rejected"
    events = RuntimeEventLogger(log_path).tail(limit=1)
    assert events[0]["command"] == "live-strategy-dry-run"
    assert events[0]["details"]["signals"] == 1


def test_live_strategy_dry_run_records_policy_and_gate_for_allowed_signal() -> None:
    candle_repo = CandleRepository("sqlite:///:memory:")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    intent_repo = LiveIntentRepository("sqlite:///:memory:")
    gateway = NoOrderGateway()
    gateway.rest_positions = []
    gateway.rest_orders = []
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candle_repo.upsert_many(crossover_candles(start))
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
    store = LiveStateStore()
    add_usdt_balance(store)
    live_repo.save_snapshot(account_id="okx_sub_main", store=store)

    result = LiveStrategyDryRunService(
        gateway=gateway,
        candle_repository=candle_repo,
        instrument_repository=instrument_repo,
        mark_price_repository=mark_repo,
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        intent_repository=intent_repo,
    ).run(
        LiveStrategyDryRunConfig(
            account_id="okx_sub_main",
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            strategy="ma-crossover",
        )
    )

    assert result.signals_count == 1
    assert result.allowed_count == 1
    assert result.rejected_count == 0
    decision = result.decisions[0]
    assert decision.risk_reason == "within risk limits"
    assert decision.policy_reason == "order_policy_passed"
    assert decision.gate_reason == "all_checks_passed"
    assert gateway.place_order_calls == 0
    assert gateway.cancel_order_calls == 0
    entries = intent_repo.list_entries(run_id=result.run_id)
    assert entries[0].status == "allowed"
    assert entries[0].policy_reason == "order_policy_passed"
    assert entries[0].gate_reason == "all_checks_passed"
