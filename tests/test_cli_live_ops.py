from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tests.cli_fakes import FakeGateway, add_usdt_balance
from app.main import AppServices, build_parser, run_command
from app.run_log import RuntimeEventLogger
from core.models import Fill, Instrument, MarkPrice, Order
from storage.live_repository import LiveStateRepository
from storage.repositories import (
    CandleRepository,
    InstrumentRepository,
    MarkPriceRepository,
)
from storage.safety_repository import SafetyRepository
from tests.fakes import (
    FakeWebSocketConnector,
    FakeWebSocketSession,
    live_store_with_position_and_order,
)






def test_run_sync_fills_command_persists_recent_rest_fills() -> None:
    gateway = FakeGateway()
    gateway.rest_fills = [
        Fill(
            account_id="okx_sub_main",
            bot_id="live_sync",
            strategy_id="exchange_sync",
            symbol="BTC-USDT-SWAP",
            run_id="live",
            fill_id="trade-1",
            client_order_id="client-1",
            side="buy",
            size=Decimal("0.03"),
            price=Decimal("70200"),
            fee=Decimal("-0.08"),
            created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
    ]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
    )
    args = build_parser().parse_args(["sync-fills", "--symbol", "BTC-USDT-SWAP", "--limit", "10"])

    output = run_command(args, services)

    assert output == "sync_fills scope=BTC-USDT-SWAP fetched=1 stored=1 matched_orders=0"
    assert gateway.recent_fill_calls == [
        {
            "account_id": "okx_sub_main",
            "inst_type": "SWAP",
            "symbol": "BTC-USDT-SWAP",
            "order_id": None,
            "limit": 10,
        }
    ]
    restored = live_repo.load_snapshot(account_id="okx_sub_main")
    assert restored.fills["trade-1"].price == Decimal("70200")


def test_run_live_sync_command_updates_public_and_private_state_summary() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    connector = FakeWebSocketConnector(
        [
            FakeWebSocketSession(
                [
                    {
                        "arg": {"channel": "tickers"},
                        "data": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "last": "70000",
                                "ts": "1717200000000",
                            }
                        ],
                    },
                    {
                        "arg": {"channel": "tickers"},
                        "data": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "last": "70100",
                                "ts": "1717200001000",
                            }
                        ],
                    },
                ]
            ),
            FakeWebSocketSession(
                [
                    {
                        "arg": {"channel": "account"},
                        "data": [
                            {
                                "uTime": "1717200001000",
                                "details": [
                                    {
                                        "ccy": "USDT",
                                        "eq": "1000",
                                        "availBal": "900",
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "arg": {"channel": "orders"},
                        "data": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "ordId": "okx-1",
                                "clOrdId": "client-1",
                                "tradeId": "trade-1",
                                "side": "buy",
                                "ordType": "market",
                                "sz": "0.1",
                                "accFillSz": "0.1",
                                "fillSz": "0.04",
                                "fillPx": "70100",
                                "fillFee": "-0.12",
                                "avgPx": "70100",
                                "state": "filled",
                                "fillTime": "1717200002000",
                                "cTime": "1717200000000",
                                "uTime": "1717200002000",
                            }
                        ],
                    },
                ]
            ),
        ]
    )
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        websocket_connector=connector,
        live_state_repository=live_repo,
    )
    args = build_parser().parse_args(
        ["live-sync", "--symbol", "BTC-USDT-SWAP", "--max-messages", "2"]
    )

    output = run_command(args, services)

    assert "live_sync mode=both" in output
    assert "symbols=BTC-USDT-SWAP" in output
    assert "public_messages=2" in output
    assert "private_messages=2" in output
    assert "tickers=1" in output
    assert "balances=1" in output
    assert "orders=1" in output
    assert "fills=1" in output
    assert "persisted=true" in output
    assert "trading_enabled=false" in output
    restored = live_repo.load_snapshot(account_id="okx_sub_main")
    assert restored.tickers["BTC-USDT-SWAP"].last_price == Decimal("70100")
    assert restored.balances["USDT"].equity == Decimal("1000")
    assert restored.orders["okx-1"].status == "filled"
    assert restored.fills["trade-1"].price == Decimal("70100")
    assert connector.urls == [
        "wss://ws.okx.com:8443/ws/v5/public",
        "wss://ws.okx.com:8443/ws/v5/private",
    ]


def test_run_live_sync_command_public_only_skips_private_connection() -> None:
    connector = FakeWebSocketConnector(
        [
            FakeWebSocketSession(
                [
                    {
                        "arg": {"channel": "tickers"},
                        "data": [
                            {
                                "instId": "ETH-USDT-SWAP",
                                "last": "3000",
                                "ts": "1717200000000",
                            }
                        ],
                    }
                ]
            )
        ]
    )
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        websocket_connector=connector,
    )
    args = build_parser().parse_args(
        ["live-sync", "--symbol", "ETH-USDT-SWAP", "--max-messages", "1", "--public-only"]
    )

    output = run_command(args, services)

    assert "live_sync mode=public" in output
    assert "public_messages=1" in output
    assert "private_messages=0" in output
    assert "persisted=false" in output
    assert len(connector.urls) == 1


def test_run_live_sync_command_can_subscribe_private_fills_channel() -> None:
    private_session = FakeWebSocketSession(
        [
            {
                "arg": {"channel": "fills", "instId": "BTC-USDT-SWAP"},
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "ordId": "okx-1",
                        "clOrdId": "client-1",
                        "tradeId": "trade-2",
                        "side": "buy",
                        "fillSz": "0.03",
                        "fillPx": "70200",
                        "ts": "1717200003000",
                    }
                ],
            }
        ]
    )
    connector = FakeWebSocketConnector([private_session])
    live_repo = LiveStateRepository("sqlite:///:memory:")
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        websocket_connector=connector,
        live_state_repository=live_repo,
    )
    args = build_parser().parse_args(
        [
            "live-sync",
            "--symbol",
            "BTC-USDT-SWAP",
            "--max-messages",
            "1",
            "--private-only",
            "--include-fills-channel",
        ]
    )

    output = run_command(args, services)

    assert "live_sync mode=private" in output
    assert "fills=1" in output
    assert "fills_channel=true" in output
    assert private_session.sent[1]["args"] == [
        {"channel": "account"},
        {"channel": "positions", "instType": "SWAP"},
        {"channel": "orders", "instType": "SWAP"},
        {"channel": "fills", "instId": "BTC-USDT-SWAP"},
    ]
    restored = live_repo.load_snapshot(account_id="okx_sub_main")
    assert restored.fills["trade-2"].price == Decimal("70200")


def test_run_live_bot_run_command_runs_bounded_read_only_loop_and_logs() -> None:
    class NoOrderGateway(FakeGateway):
        def __init__(self) -> None:
            super().__init__()
            self.place_order_calls = 0
            self.cancel_order_calls = 0

        def place_order(self, *args, **kwargs):
            self.place_order_calls += 1
            raise AssertionError("live-bot-run must not place orders")

        def cancel_order(self, *args, **kwargs):
            self.cancel_order_calls += 1
            raise AssertionError("live-bot-run must not cancel orders")

    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    gateway = NoOrderGateway()
    gateway.rest_positions = []
    gateway.rest_orders = []
    connector = FakeWebSocketConnector(
        [
            FakeWebSocketSession(
                [
                    {
                        "arg": {"channel": "tickers"},
                        "data": [{"instId": "BTC-USDT-SWAP", "last": "70000", "ts": "1717200000000"}],
                    }
                ]
            ),
            FakeWebSocketSession(
                [
                    {
                        "arg": {"channel": "account"},
                        "data": [{"details": [{"ccy": "USDT", "eq": "1000", "availEq": "900"}], "uTime": "1717200000000"}],
                    }
                ]
            ),
        ]
    )
    log_path = Path(f"test-runtime-events-cli-live-bot-run-{uuid4().hex}.jsonl")
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        websocket_connector=connector,
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        mark_price_repository=mark_repo,
        runtime_logger=RuntimeEventLogger(log_path),
    )
    args = build_parser().parse_args(
        [
            "live-bot-run",
            "--symbol",
            "BTC-USDT-SWAP",
            "--max-iterations",
            "1",
            "--interval-seconds",
            "0",
        ]
    )

    output = run_command(args, services)

    assert "live_bot_run iterations=1 completed=1 failed=0" in output
    assert "last_gate_status=blocked" in output
    assert "last_gate_reason=missing_mark_price" in output
    assert gateway.place_order_calls == 0
    assert gateway.cancel_order_calls == 0
    assert live_repo.load_snapshot(account_id="okx_sub_main").balances["USDT"].equity == Decimal("1000")
    events = RuntimeEventLogger(log_path).tail(limit=2)
    assert events[0]["command"] == "live-bot-once"
    assert events[1]["command"] == "live-bot-run"


def test_run_live_sync_command_rejects_conflicting_modes() -> None:
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        websocket_connector=FakeWebSocketConnector([]),
    )
    args = build_parser().parse_args(["live-sync", "--public-only", "--private-only"])

    try:
        run_command(args, services)
    except ValueError as exc:
        assert "cannot be used together" in str(exc)
    else:
        raise AssertionError("expected conflicting live-sync modes to be rejected")


def test_run_live_reconcile_command_reports_clean_snapshot() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}]
    gateway.rest_orders = [{"ordId": "okx-1"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    live_store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    live_repo.save_snapshot(account_id="okx_sub_main", store=live_store)
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
    )
    args = build_parser().parse_args(["live-reconcile", "--account-id", "okx_sub_main"])

    output = run_command(args, services)

    assert output == (
        "live_reconcile status=clean position_issues=0 "
        "missing_orders_on_exchange=0 missing_orders_locally=0 trading_allowed=true"
    )


def test_run_live_reconcile_command_blocks_on_snapshot_mismatch() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "short", "pos": "-0.2"}]
    gateway.rest_orders = [{"ordId": "exchange-only"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    live_store = live_store_with_position_and_order(order_id="local-only", direction="long", size="0.1")
    live_repo.save_snapshot(account_id="okx_sub_main", store=live_store)
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
    )
    args = build_parser().parse_args(["live-reconcile"])

    output = run_command(args, services)

    assert "live_reconcile status=blocked" in output
    assert "position_issues=2" in output
    assert "missing_orders_on_exchange=1" in output
    assert "missing_orders_locally=1" in output
    assert "trading_allowed=false" in output


def test_prelive_readiness_reports_ready_when_local_state_is_available() -> None:
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    live_repo = LiveStateRepository("sqlite:///:memory:")
    live_store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
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
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        instrument_repository=instrument_repo,
        mark_price_repository=mark_repo,
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
        runtime_logger=RuntimeEventLogger(Path("test-runtime-events.jsonl")),
        default_symbols=["BTC-USDT-SWAP"],
    )

    output = run_command(build_parser().parse_args(["prelive-readiness"]), services)

    assert "prelive_readiness status=ready" in output
    assert "manual_paused=false" in output
    assert "runtime_log=configured" in output
    assert "instruments=ok" in output
    assert "mark_prices=market_data_fresh" in output
    assert "balance_snapshot=available" in output
    assert "issues=none" in output


def test_prelive_readiness_reports_missing_local_requirements() -> None:
    safety_repo = SafetyRepository("sqlite:///:memory:")
    safety_repo.set_pause(account_id="okx_sub_main", paused=True, reason="operator_stop")
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        instrument_repository=InstrumentRepository("sqlite:///:memory:"),
        mark_price_repository=MarkPriceRepository("sqlite:///:memory:"),
        live_state_repository=LiveStateRepository("sqlite:///:memory:"),
        safety_repository=safety_repo,
        runtime_logger=None,
        default_symbols=["BTC-USDT-SWAP"],
    )

    output = run_command(build_parser().parse_args(["prelive-readiness"]), services)

    assert "prelive_readiness status=blocked" in output
    assert "manual_paused=true" in output
    assert "runtime_log=disabled" in output
    assert "instruments=missing:BTC-USDT-SWAP" in output
    assert "mark_prices=missing_mark_price:missing=BTC-USDT-SWAP" in output
    assert "balance_snapshot=missing_balance_snapshot" in output
    assert "manual_pause" in output
    assert "runtime_log_disabled" in output
    assert "missing_instruments" in output


def test_prelive_readiness_reports_stale_mark_price() -> None:
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    live_repo = LiveStateRepository("sqlite:///:memory:")
    live_store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
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
                updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ]
    )
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        instrument_repository=instrument_repo,
        mark_price_repository=mark_repo,
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
        runtime_logger=RuntimeEventLogger(Path("test-runtime-events.jsonl")),
        default_symbols=["BTC-USDT-SWAP"],
    )

    output = run_command(build_parser().parse_args(["prelive-readiness"]), services)

    assert "prelive_readiness status=blocked" in output
    assert "mark_prices=stale_mark_price:stale=BTC-USDT-SWAP" in output
    assert "issues=stale_mark_price" in output


def test_prelive_readiness_is_local_read_only() -> None:
    class ExplodingGateway:
        def __getattr__(self, name):
            raise AssertionError(f"gateway should not be used: {name}")

    class ExplodingRuntimeLogger(RuntimeEventLogger):
        def record(self, *, command: str, outcome: str, details: dict | None = None) -> None:
            raise AssertionError("prelive-readiness must not write runtime events")

    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    live_store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
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
    services = AppServices(
        gateway=ExplodingGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        instrument_repository=instrument_repo,
        mark_price_repository=mark_repo,
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        runtime_logger=ExplodingRuntimeLogger(Path("test-runtime-events.jsonl")),
        default_symbols=["BTC-USDT-SWAP"],
    )

    output = run_command(build_parser().parse_args(["prelive-readiness"]), services)

    assert "prelive_readiness status=ready" in output
    assert safety_repo.get_equity_risk_state(account_id="okx_sub_main", currency="USDT") is None


def test_run_trading_gate_command_allows_clean_state() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    add_usdt_balance(store)
    live_repo.save_snapshot(account_id="okx_sub_main", store=store)
    gateway.rest_orders = [{"ordId": "okx-1"}]
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )

    output = run_command(build_parser().parse_args(["trading-gate"]), services)

    assert "trading_gate status=allowed" in output
    assert "reason=all_checks_passed" in output
    assert "equity_risk=within_equity_limits" in output
    assert "trading_allowed=true" in output


def test_run_trading_gate_command_blocks_when_manually_paused() -> None:
    safety_repo = SafetyRepository("sqlite:///:memory:")
    safety_repo.set_pause(account_id="okx_sub_main", paused=True, reason="manual")
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=LiveStateRepository("sqlite:///:memory:"),
        safety_repository=safety_repo,
    )

    output = run_command(build_parser().parse_args(["trading-gate"]), services)

    assert "trading_gate status=blocked" in output
    assert "reason=manual_pause" in output
    assert "manual_paused=true" in output
    assert "trading_allowed=false" in output


def test_run_trading_gate_command_blocks_on_reconciliation_mismatch() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "short", "pos": "-0.2"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    store = live_store_with_position_and_order(order_id="local-only", direction="long", size="0.1")
    add_usdt_balance(store)
    live_repo.save_snapshot(account_id="okx_sub_main", store=store)
    gateway.rest_orders = [{"ordId": "exchange-only"}]
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )

    output = run_command(build_parser().parse_args(["trading-gate"]), services)

    assert "trading_gate status=blocked" in output
    assert "reason=reconciliation_blocked" in output
    assert "position_issues=2" in output
    assert "missing_orders_on_exchange=1" in output
    assert "missing_orders_locally=1" in output
    assert "trading_allowed=false" in output


def test_run_trading_gate_command_blocks_without_equity_snapshot() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    live_repo.save_snapshot(
        account_id="okx_sub_main",
        store=live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1"),
    )
    gateway.rest_orders = [{"ordId": "okx-1"}]
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )

    output = run_command(build_parser().parse_args(["trading-gate"]), services)

    assert "trading_gate status=blocked" in output
    assert "reason=missing_equity_snapshot" in output
    assert "equity_risk=missing_equity_snapshot" in output
    assert "trading_allowed=false" in output


def test_run_trading_gate_command_blocks_without_mark_price_snapshot() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}]
    gateway.rest_orders = [{"ordId": "okx-1"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    add_usdt_balance(store)
    live_repo.save_snapshot(account_id="okx_sub_main", store=store)
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
        mark_price_repository=MarkPriceRepository("sqlite:///:memory:"),
        default_symbols=["BTC-USDT-SWAP"],
    )

    output = run_command(build_parser().parse_args(["trading-gate"]), services)

    assert "trading_gate status=blocked" in output
    assert "reason=missing_mark_price" in output
    assert "market_data=missing_mark_price" in output
    assert "trading_allowed=false" in output


def test_run_live_order_check_allows_safe_market_open_intent() -> None:
    gateway = FakeGateway()
    gateway.rest_positions = [{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}]
    gateway.rest_orders = [{"ordId": "okx-1"}]
    live_repo = LiveStateRepository("sqlite:///:memory:")
    store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    add_usdt_balance(store)
    live_repo.save_snapshot(account_id="okx_sub_main", store=store)
    services = AppServices(
        gateway=gateway,
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )
    args = build_parser().parse_args(
        [
            "live-order-check",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.1",
            "--client-order-id",
            "check-1",
        ]
    )

    output = run_command(args, services)

    assert "live_order_check status=allowed" in output
    assert "policy=order_policy_passed" in output
    assert "gate=all_checks_passed" in output
    assert "trading_allowed=true" in output


def test_run_live_order_check_rejects_policy_before_gateway_reconciliation() -> None:
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=LiveStateRepository("sqlite:///:memory:"),
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )
    args = build_parser().parse_args(
        [
            "live-order-check",
            "--symbol",
            "SOL-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.1",
        ]
    )

    output = run_command(args, services)

    assert "live_order_check status=policy_rejected" in output
    assert "reason=symbol_not_allowed" in output
    assert "gate=not_checked" in output
    assert "trading_allowed=false" in output


def test_run_live_order_check_rejects_missing_instrument_spec_before_gateway_reconciliation() -> None:
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        instrument_repository=InstrumentRepository("sqlite:///:memory:"),
        live_state_repository=LiveStateRepository("sqlite:///:memory:"),
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )
    args = build_parser().parse_args(
        [
            "live-order-check",
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

    output = run_command(args, services)

    assert "live_order_check status=policy_rejected" in output
    assert "reason=instrument_spec_missing" in output
    assert "gate=not_checked" in output
    assert "trading_allowed=false" in output


def test_run_live_order_check_rejects_duplicate_active_client_order_id() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    add_usdt_balance(store)
    store.upsert_order(
        Order(
            account_id="okx_sub_main",
            bot_id="okx_perp_bot_main",
            strategy_id="manual_live_check",
            symbol="BTC-USDT-SWAP",
            run_id="live-check",
            order_id="okx-duplicate",
            client_order_id="check-duplicate",
            side="buy",
            order_type="market",
            size=Decimal("0.1"),
            status="submitted",
        )
    )
    live_repo.save_snapshot(account_id="okx_sub_main", store=store)
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
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
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        instrument_repository=instrument_repo,
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )
    args = build_parser().parse_args(
        [
            "live-order-check",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.1",
            "--client-order-id",
            "check-duplicate",
        ]
    )

    output = run_command(args, services)

    assert "live_order_check status=local_state_rejected" in output
    assert "reason=duplicate_client_order_id" in output
    assert "gate=not_checked" in output
    assert "trading_allowed=false" in output


def test_run_live_order_check_rejects_negative_size_by_policy() -> None:
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=LiveStateRepository("sqlite:///:memory:"),
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )
    args = build_parser().parse_args(
        [
            "live-order-check",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "-0.1",
        ]
    )

    output = run_command(args, services)

    assert "live_order_check status=policy_rejected" in output
    assert "reason=size_must_be_positive" in output
    assert "gate=not_checked" in output


def test_run_live_order_check_rejects_invalid_decimal_size() -> None:
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=LiveStateRepository("sqlite:///:memory:"),
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )
    args = build_parser().parse_args(
        [
            "live-order-check",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "not-a-number",
        ]
    )

    try:
        run_command(args, services)
    except ValueError as exc:
        assert "size must be a valid decimal" in str(exc)
    else:
        raise AssertionError("expected invalid size to be rejected")


def test_run_live_order_check_rejects_market_price_by_policy() -> None:
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=LiveStateRepository("sqlite:///:memory:"),
        safety_repository=SafetyRepository("sqlite:///:memory:"),
    )
    args = build_parser().parse_args(
        [
            "live-order-check",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.1",
            "--price",
            "70000",
        ]
    )

    output = run_command(args, services)

    assert "live_order_check status=policy_rejected" in output
    assert "reason=market_order_must_not_have_price" in output
    assert "gate=not_checked" in output
