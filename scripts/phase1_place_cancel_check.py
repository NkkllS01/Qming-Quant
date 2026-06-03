from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.phase1_cli import build_gateway, require_okx_success
from core.models import OrderIntent


def main() -> None:
    try:
        _run_check()
    except Exception as exc:
        print(f"FAIL phase1 place/cancel check: {exc}")
        raise SystemExit(1) from exc
    print("PASS phase1 place/cancel check")


def _run_check() -> None:
    settings = Settings.from_env()
    gateway = build_gateway(settings)
    server_time = gateway.server_time()
    if not server_time.get("data"):
        raise RuntimeError("OKX server time response has no data")
    auth_response = gateway.balance()
    require_okx_success(auth_response, "auth")

    intent = OrderIntent(
        account_id="okx_demo",
        bot_id="phase1_check",
        strategy_id="manual_phase1",
        symbol="BTC-USDT-SWAP",
        run_id="phase1-check",
        side="buy",
        position_action="open",
        order_type="market",
        size=Decimal("0.01"),
        price=None,
        reduce_only=False,
        client_order_id=f"p1{uuid4().hex[:24]}",
    )
    place_response = gateway.place_order(intent, td_mode="isolated")
    require_okx_success(place_response, "place")
    order_id = _response_order_id(place_response)
    cancel_response = gateway.cancel_order(symbol=intent.symbol, order_id=order_id)
    require_okx_success(cancel_response, "cancel")


def _response_order_id(response: dict) -> str:
    rows = response.get("data", [])
    if not rows or not rows[0].get("ordId"):
        raise RuntimeError(f"place order response has no ordId: {response}")
    return str(rows[0]["ordId"])


if __name__ == "__main__":
    main()
