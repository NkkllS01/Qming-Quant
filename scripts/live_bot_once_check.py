from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.run_log import RuntimeEventLogger
from exchanges.okx.websocket import OKXWebSocketClient, OKXWebSocketConfig
from live.bot import LiveBotConfig, LiveBotLoop
from storage.live_repository import LiveStateRepository
from storage.repositories import MarkPriceRepository
from storage.safety_repository import SafetyRepository
from tests.fakes import FakePrivateGateway, FakeWebSocketConnector, FakeWebSocketSession


class FakeLiveGateway(FakePrivateGateway):
    def __init__(self) -> None:
        super().__init__(
            positions=[{"instId": "BTC-USDT-SWAP", "pos": "0.1", "posSide": "long"}],
            orders=[{"ordId": "okx-1", "clOrdId": "client-1"}],
        )
        self.public_ws = OKXWebSocketClient(OKXWebSocketConfig())
        self.private_ws = OKXWebSocketClient(
            OKXWebSocketConfig(api_key="key", secret_key="secret", passphrase="pass")
        )
        self.place_order_calls = 0
        self.cancel_order_calls = 0
        self.recent_fill_calls = 0

    def place_order(self, *args, **kwargs):
        self.place_order_calls += 1
        raise RuntimeError("live_bot_once_check must remain read-only")

    def cancel_order(self, *args, **kwargs):
        self.cancel_order_calls += 1
        raise RuntimeError("live_bot_once_check must remain read-only")

    def recent_fills(self, *args, **kwargs):
        self.recent_fill_calls += 1
        return []


def main() -> None:
    try:
        _run_check()
    except Exception as exc:
        print(f"FAIL live bot once check: {exc}")
        raise SystemExit(1) from exc
    print("PASS live bot once check")


def _run_check() -> None:
    database_url = "sqlite:///:memory:"
    live_repo = LiveStateRepository(database_url)
    safety_repo = SafetyRepository(database_url)
    gateway = FakeLiveGateway()
    log_path = Path(f"test-runtime-events-live-bot-{uuid4().hex}.jsonl")
    connector = FakeWebSocketConnector(
        [
            FakeWebSocketSession(
                [
                    {
                        "arg": {"channel": "tickers"},
                        "data": [{"instId": "BTC-USDT-SWAP", "last": "70000", "ts": "1717200000000"}],
                    },
                    {
                        "arg": {"channel": "tickers"},
                        "data": [{"instId": "BTC-USDT-SWAP", "last": "70001", "ts": "1717200001000"}],
                    },
                    {
                        "arg": {"channel": "tickers"},
                        "data": [{"instId": "BTC-USDT-SWAP", "last": "70002", "ts": "1717200002000"}],
                    },
                    {
                        "arg": {"channel": "tickers"},
                        "data": [{"instId": "BTC-USDT-SWAP", "last": "70003", "ts": "1717200003000"}],
                    },
                ]
            ),
            FakeWebSocketSession(
                [
                    {
                        "arg": {"channel": "account"},
                        "data": [{"details": [{"ccy": "USDT", "eq": "1000", "availEq": "900"}], "uTime": "1717200000000"}],
                    },
                    {
                        "arg": {"channel": "positions"},
                        "data": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "pos": "0.1",
                                "posSide": "long",
                                "avgPx": "70000",
                                "markPx": "70100",
                                "upl": "10",
                                "lever": "1",
                                "uTime": "1717200001000",
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
                                "side": "buy",
                                "ordType": "market",
                                "sz": "0.1",
                                "accFillSz": "0",
                                "state": "live",
                                "cTime": "1717200000000",
                                "uTime": "1717200001000",
                            }
                        ],
                    },
                    {
                        "arg": {"channel": "fills", "instId": "BTC-USDT-SWAP"},
                        "data": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "ordId": "okx-1",
                                "clOrdId": "client-1",
                                "tradeId": "trade-1",
                                "side": "buy",
                                "fillSz": "0.03",
                                "fillPx": "70200",
                                "ts": "1717200003000",
                            }
                        ],
                    },
                ]
            ),
        ]
    )
    result = LiveBotLoop(
        config=LiveBotConfig(
            account_id="okx_sub_main",
            symbols=["BTC-USDT-SWAP"],
            include_fills_channel=True,
            max_messages_per_connection=4,
        ),
        gateway=gateway,
        connector=connector,
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        mark_price_repository=MarkPriceRepository(database_url),
        runtime_logger=RuntimeEventLogger(log_path),
    ).run_once()
    store = live_repo.load_snapshot(account_id="okx_sub_main")
    if result.sync.tickers_count != 1 or result.sync.balances_count != 1:
        raise RuntimeError(f"unexpected sync counts: {result.sync}")
    if not store.positions or not store.orders or not store.fills:
        raise RuntimeError("expected persisted position, order, and fill snapshots")
    if result.gate is None or result.gate.reason != "missing_mark_price":
        raise RuntimeError(f"expected missing mark price gate block, got {result.gate}")
    if gateway.place_order_calls or gateway.cancel_order_calls:
        raise RuntimeError("live bot check called order placement or cancellation")
    latest_event = RuntimeEventLogger(log_path).tail(limit=1)[0]
    if latest_event["command"] != "live-bot-once":
        raise RuntimeError(f"unexpected runtime event: {latest_event}")


if __name__ == "__main__":
    main()
