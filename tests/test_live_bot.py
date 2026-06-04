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

    def place_order(self, *args, **kwargs):
        self.order_submissions += 1
        raise AssertionError("live bot loop must not place orders")

    def cancel_order(self, *args, **kwargs):
        self.order_cancellations += 1
        raise AssertionError("live bot loop must not cancel orders")


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
