from decimal import Decimal

from app.config import Settings
from app.phase1_cli import build_gateway, build_parser, run_command
from core.models import OrderIntent


def test_phase1_build_gateway_requires_demo_mode() -> None:
    settings = Settings(
        okx_api_key="key",
        okx_secret_key="secret",
        okx_passphrase="pass",
        okx_simulated_trading=False,
    )

    try:
        build_gateway(settings)
    except RuntimeError as exc:
        assert "OKX_SIMULATED_TRADING=1" in str(exc)
    else:
        raise AssertionError("expected Phase 1 gateway to require demo mode")


def test_phase1_place_command_submits_one_market_order() -> None:
    gateway = FakeGateway()
    args = build_parser().parse_args(
        [
            "place",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--size",
            "0.01",
            "--client-order-id",
            "phase1-client",
        ]
    )

    output = run_command(args, gateway)

    assert output == (
        "phase1_place status=sent symbol=BTC-USDT-SWAP "
        "order_id=okx-1 client_order_id=phase1-client"
    )
    assert gateway.placed[0]["td_mode"] == "isolated"
    assert gateway.placed[0]["intent"].size == Decimal("0.01")
    assert gateway.placed[0]["intent"].order_type == "market"


def test_phase1_cancel_command_cancels_one_order() -> None:
    gateway = FakeGateway()
    args = build_parser().parse_args(
        ["cancel", "--symbol", "BTC-USDT-SWAP", "--client-order-id", "phase1-client"]
    )

    output = run_command(args, gateway)

    assert output == (
        "phase1_cancel status=sent symbol=BTC-USDT-SWAP "
        "order_id=none client_order_id=phase1-client"
    )
    assert gateway.cancelled == [
        {
            "symbol": "BTC-USDT-SWAP",
            "order_id": None,
            "client_order_id": "phase1-client",
        }
    ]


class FakeGateway:
    def __init__(self) -> None:
        self.placed: list[dict] = []
        self.cancelled: list[dict] = []

    def place_order(self, intent: OrderIntent, *, td_mode: str) -> dict:
        self.placed.append({"intent": intent, "td_mode": td_mode})
        return {"data": [{"ordId": "okx-1"}]}

    def cancel_order(
        self,
        *,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        self.cancelled.append(
            {
                "symbol": symbol,
                "order_id": order_id,
                "client_order_id": client_order_id,
            }
        )
        return {"data": [{"clOrdId": client_order_id}]}
