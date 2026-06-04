from pathlib import Path
import os

from app.run_log import RuntimeEventLogger
from exchanges.okx.websocket import OKXWebSocketClient, OKXWebSocketConfig
from live.bot import LiveBotConfig, LiveBotLoop
from storage.live_repository import LiveStateRepository
from storage.repositories import MarkPriceRepository
from storage.safety_repository import SafetyRepository
from tests.fakes import FakePrivateGateway, FakeWebSocketConnector, FakeWebSocketSession


class FakeLiveGateway(FakePrivateGateway):
    def __init__(self) -> None:
        super().__init__(positions=[], orders=[])
        self.public_ws = OKXWebSocketClient(OKXWebSocketConfig())
        self.private_ws = OKXWebSocketClient(
            OKXWebSocketConfig(api_key="key", secret_key="secret", passphrase="pass")
        )
        self.order_submissions = 0
        self.order_cancellations = 0
        self.recent_fill_calls: list[dict] = []

    def place_order(self, *args, **kwargs):
        self.order_submissions += 1
        raise AssertionError("live bot loop must not place orders")

    def cancel_order(self, *args, **kwargs):
        self.order_cancellations += 1
        raise AssertionError("live bot loop must not cancel orders")

    def recent_fills(
        self,
        *,
        account_id: str,
        inst_type: str = "SWAP",
        symbol: str | None = None,
        order_id: str | None = None,
        limit: int = 100,
    ) -> list:
        self.recent_fill_calls.append(
            {
                "account_id": account_id,
                "inst_type": inst_type,
                "symbol": symbol,
                "order_id": order_id,
                "limit": limit,
            }
        )
        return []


def _log_path(name: str) -> Path:
    path = Path(f"test-runtime-events-{name}-{os.getpid()}.jsonl")
    if path.exists():
        path.unlink()
    return path


def test_live_bot_run_once_syncs_state_evaluates_gate_and_logs() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    log_path = _log_path("live-bot")
    gateway = FakeLiveGateway()
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
    loop = LiveBotLoop(
        config=LiveBotConfig(account_id="okx_sub_main", symbols=["BTC-USDT-SWAP"]),
        gateway=gateway,
        connector=connector,
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        mark_price_repository=mark_repo,
        runtime_logger=RuntimeEventLogger(log_path),
    )

    result = loop.run_once()

    assert result.sync.persisted is True
    assert result.fill_backfill.fetched_count == 0
    assert result.sync.tickers_count == 1
    assert result.sync.balances_count == 1
    assert result.gate is not None
    assert result.gate.status == "blocked"
    assert result.gate.reason == "missing_mark_price"
    assert gateway.order_submissions == 0
    assert gateway.order_cancellations == 0
    assert live_repo.load_snapshot(account_id="okx_sub_main").balances["USDT"].equity == 1000
    events = RuntimeEventLogger(log_path).tail(limit=1)
    assert events[0]["command"] == "live-bot-once"
    assert events[0]["details"]["gate_status"] == "blocked"
    assert events[0]["details"]["fill_backfill_fetched"] == 0
    assert gateway.recent_fill_calls == [
        {
            "account_id": "okx_sub_main",
            "inst_type": "SWAP",
            "symbol": "BTC-USDT-SWAP",
            "order_id": None,
            "limit": 100,
        }
    ]


def test_live_bot_run_once_can_skip_gate() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    gateway = FakeLiveGateway()
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
    loop = LiveBotLoop(
        config=LiveBotConfig(account_id="okx_sub_main", symbols=["BTC-USDT-SWAP"], evaluate_gate=False),
        gateway=gateway,
        connector=connector,
        live_state_repository=live_repo,
        safety_repository=SafetyRepository("sqlite:///:memory:"),
        mark_price_repository=None,
        runtime_logger=RuntimeEventLogger(_log_path("live-bot-skip-gate")),
    )

    result = loop.run_once()

    assert result.gate is None
    assert result.sync.persisted is True


def test_live_bot_run_retries_after_disconnection_and_keeps_logging_blocked_gate() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    mark_repo = MarkPriceRepository("sqlite:///:memory:")
    log_path = _log_path("live-bot-run")
    gateway = FakeLiveGateway()
    connector = FakeWebSocketConnector(
        [
            FakeWebSocketSession([], fail_on_receive=True),
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
    loop = LiveBotLoop(
        config=LiveBotConfig(
            account_id="okx_sub_main",
            symbols=["BTC-USDT-SWAP"],
            max_iterations=2,
            interval_seconds=0,
        ),
        gateway=gateway,
        connector=connector,
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        mark_price_repository=mark_repo,
        runtime_logger=RuntimeEventLogger(log_path),
    )

    summary = loop.run()

    assert summary.iterations == 2
    assert summary.completed_iterations == 1
    assert summary.failed_iterations == 1
    assert summary.last_result is not None
    assert summary.last_result.gate is not None
    assert summary.last_result.gate.status == "blocked"
    assert gateway.order_submissions == 0
    assert gateway.order_cancellations == 0
    assert live_repo.load_snapshot(account_id="okx_sub_main").balances["USDT"].equity == 1000
    events = RuntimeEventLogger(log_path).tail(limit=3)
    assert [event["command"] for event in events] == ["live-bot-run-iteration", "live-bot-once", "live-bot-run"]
    assert events[0]["outcome"] == "failed"
    assert events[1]["details"]["gate_status"] == "blocked"
    assert events[2]["details"]["completed_iterations"] == 1
