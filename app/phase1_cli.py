from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from app.config import Settings
from core.models import OrderIntent
from exchanges.okx.gateway import OKXGateway
from exchanges.okx.rest import OKXRestClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phase1", description="OKX demo place/cancel CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("auth", help="Verify OKX demo private API auth")

    place = subparsers.add_parser("place", help="Place one OKX demo order")
    place.add_argument("--symbol", default="BTC-USDT-SWAP")
    place.add_argument("--side", choices=["buy", "sell"], required=True)
    place.add_argument("--size", required=True)
    place.add_argument("--td-mode", default="isolated")
    place.add_argument("--client-order-id", default=None)

    cancel = subparsers.add_parser("cancel", help="Cancel one OKX demo order")
    cancel.add_argument("--symbol", default="BTC-USDT-SWAP")
    cancel.add_argument("--order-id", default=None)
    cancel.add_argument("--client-order-id", default=None)
    return parser


def build_gateway(settings: Settings) -> OKXGateway:
    _require_demo_settings(settings)
    rest = OKXRestClient(
        api_key=settings.okx_api_key,
        secret_key=settings.okx_secret_key,
        passphrase=settings.okx_passphrase,
        base_url=settings.okx_base_url,
        simulated_trading=settings.okx_simulated_trading,
    )
    return OKXGateway(rest)


def run_command(args: argparse.Namespace, gateway: OKXGateway) -> str:
    if args.command == "auth":
        return _auth_check(gateway)
    if args.command == "place":
        return _place_order(args, gateway)
    if args.command == "cancel":
        return _cancel_order(args, gateway)
    raise ValueError(f"unsupported command: {args.command}")


def _auth_check(gateway: OKXGateway) -> str:
    response = gateway.balance()
    require_okx_success(response, "auth")
    return "phase1_auth status=ok"


def _place_order(args: argparse.Namespace, gateway: OKXGateway) -> str:
    intent = OrderIntent(
        account_id="okx_demo",
        bot_id="phase1_cli",
        strategy_id="manual_phase1",
        symbol=args.symbol,
        run_id="phase1-cli",
        side=args.side,
        position_action="open",
        order_type="market",
        size=_parse_decimal(args.size),
        price=None,
        reduce_only=False,
        client_order_id=args.client_order_id or f"p1{uuid4().hex[:24]}",
    )
    response = gateway.place_order(intent, td_mode=args.td_mode)
    require_okx_success(response, "place")
    order_id = _first_data_value(response, "ordId", "none")
    return f"phase1_place status=sent symbol={args.symbol} order_id={order_id} client_order_id={intent.client_order_id}"


def _cancel_order(args: argparse.Namespace, gateway: OKXGateway) -> str:
    if args.order_id is None and args.client_order_id is None:
        raise ValueError("cancel requires order-id or client-order-id")
    response = gateway.cancel_order(
        symbol=args.symbol,
        order_id=args.order_id,
        client_order_id=args.client_order_id,
    )
    require_okx_success(response, "cancel")
    order_id = _first_data_value(response, "ordId", args.order_id or "none")
    client_order_id = _first_data_value(response, "clOrdId", args.client_order_id or "none")
    return f"phase1_cancel status=sent symbol={args.symbol} order_id={order_id} client_order_id={client_order_id}"


def _require_demo_settings(settings: Settings) -> None:
    if not settings.okx_api_key or not settings.okx_secret_key or not settings.okx_passphrase:
        raise RuntimeError("OKX_API_KEY, OKX_SECRET_KEY and OKX_PASSPHRASE are required")
    if not settings.okx_simulated_trading:
        raise RuntimeError("OKX_SIMULATED_TRADING=1 is required for Phase 1 demo trading")


def _parse_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("size must be a valid decimal") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("size must be a positive finite decimal")
    return parsed


def require_okx_success(response: dict, action: str) -> None:
    if response.get("code") != "0":
        raise RuntimeError(f"OKX {action} failed: {response}")


def _first_data_value(response: dict, key: str, default: str) -> str:
    rows = response.get("data", [])
    if not rows:
        return default
    value = rows[0].get(key)
    return str(value) if value else default


def main() -> None:
    args = build_parser().parse_args()
    print(run_command(args, build_gateway(Settings.from_env())))


if __name__ == "__main__":
    main()
