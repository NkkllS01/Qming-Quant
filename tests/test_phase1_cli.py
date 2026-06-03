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


def test_phase1_auth_command_checks_private_balance_api() -> None:
    gateway = FakeGateway()
    args = build_parser().parse_args(["auth"])

    output = run_command(args, gateway)

    assert output == "phase1_auth status=ok"
    assert gateway.balance_called is True


def test_phase1_auth_command_rejects_okx_error_code() -> None:
    gateway = FakeGateway(balance_response={"code": "50113", "msg": "Invalid sign"})
    args = build_parser().parse_args(["auth"])

    try:
        run_command(args, gateway)
    except RuntimeError as exc:
        assert "OKX auth failed" in str(exc)
    else:
        raise AssertionError("expected auth command to reject OKX error code")


def test_phase1_auth_command_rejects_missing_okx_code() -> None:
    gateway = FakeGateway(balance_response={"data": []})
    args = build_parser().parse_args(["auth"])

    try:
        run_command(args, gateway)
    except RuntimeError as exc:
        assert "OKX auth failed" in str(exc)
    else:
        raise AssertionError("expected auth command to require OKX success code")


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


def test_phase1_place_command_rejects_okx_error_code() -> None:
    gateway = FakeGateway(place_response={"code": "51000", "msg": "Order failed"})
    args = build_parser().parse_args(["place", "--side", "buy", "--size", "0.01"])

    try:
        run_command(args, gateway)
    except RuntimeError as exc:
        assert "OKX place failed" in str(exc)
    else:
        raise AssertionError("expected place command to reject OKX error code")


def test_phase1_cancel_command_rejects_okx_error_code() -> None:
    gateway = FakeGateway(cancel_response={"code": "51400", "msg": "Cancel failed"})
    args = build_parser().parse_args(["cancel", "--client-order-id", "phase1-client"])

    try:
        run_command(args, gateway)
    except RuntimeError as exc:
        assert "OKX cancel failed" in str(exc)
    else:
        raise AssertionError("expected cancel command to reject OKX error code")


class FakeGateway:
    def __init__(
        self,
        *,
        balance_response: dict | None = None,
        place_response: dict | None = None,
        cancel_response: dict | None = None,
    ) -> None:
        self.placed: list[dict] = []
        self.cancelled: list[dict] = []
        self.balance_called = False
        self.balance_response = balance_response or {"code": "0", "data": [{"ccy": "USDT"}]}
        self.place_response = place_response or {"code": "0", "data": [{"ordId": "okx-1"}]}
        self.cancel_response = cancel_response or {"code": "0", "data": [{"clOrdId": "phase1-client"}]}

    def balance(self) -> dict:
        self.balance_called = True
        return self.balance_response

    def place_order(self, intent: OrderIntent, *, td_mode: str) -> dict:
        self.placed.append({"intent": intent, "td_mode": td_mode})
        return self.place_response

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
        return self.cancel_response
