from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import AppServices, build_parser, run_command
from core.models import Instrument, MarkPrice, Order
from live.state import AccountBalance, LiveStateStore
from storage.live_repository import LiveStateRepository
from storage.repositories import CandleRepository, InstrumentRepository, MarkPriceRepository
from storage.safety_repository import SafetyRepository


def main() -> None:
    try:
        _run_check()
    except Exception as exc:
        print(f"FAIL prelive order check: {exc}")
        raise SystemExit(1) from exc
    print("PASS prelive order check")


def _run_check() -> None:
    _assert_contains(_run_allowed_check(), "live_order_check status=allowed")
    _assert_contains(_run_invalid_client_order_id_check(), "reason=invalid_client_order_id")
    _assert_contains(_run_duplicate_check(), "reason=duplicate_client_order_id")
    _assert_contains(_run_lot_size_check(), "reason=size_not_multiple_of_lot_size")


def _run_allowed_check() -> str:
    services = _services()
    args = _parser().parse_args(
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
            "prelive-ok",
        ]
    )
    return run_command(args, services)


def _run_duplicate_check() -> str:
    services = _services(client_order_id="prelive-duplicate")
    args = _parser().parse_args(
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
            "prelive-duplicate",
        ]
    )
    return run_command(args, services)


def _run_invalid_client_order_id_check() -> str:
    services = _services()
    args = _parser().parse_args(
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
            "bad id",
        ]
    )
    return run_command(args, services)


def _run_lot_size_check() -> str:
    services = _services()
    args = _parser().parse_args(
        [
            "live-order-check",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.015",
        ]
    )
    return run_command(args, services)


def _services(*, client_order_id: str | None = None) -> AppServices:
    database_url = "sqlite:///:memory:"
    live_repo = LiveStateRepository(database_url)
    instrument_repo = InstrumentRepository(database_url)
    mark_repo = MarkPriceRepository(database_url)
    _seed_live_state(live_repo, client_order_id=client_order_id)
    _seed_instrument(instrument_repo)
    mark_repo.upsert_many(
        [
            MarkPrice(
                symbol="BTC-USDT-SWAP",
                mark_price=Decimal("70000"),
                updated_at=datetime.now(timezone.utc),
            )
        ]
    )
    return AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository(database_url),
        instrument_repository=instrument_repo,
        live_state_repository=live_repo,
        safety_repository=SafetyRepository(database_url),
        mark_price_repository=mark_repo,
        default_symbols=["BTC-USDT-SWAP"],
    )


def _seed_live_state(repo: LiveStateRepository, *, client_order_id: str | None) -> None:
    now = datetime.now(timezone.utc)
    store = LiveStateStore()
    store.upsert_balance(AccountBalance(currency="USDT", equity=Decimal("1000"), available=Decimal("900")))
    if client_order_id is not None:
        store.upsert_order(
            Order(
                account_id="okx_sub_main",
                bot_id="okx_perp_bot_main",
                strategy_id="manual_live_check",
                symbol="BTC-USDT-SWAP",
                run_id="live-check",
                order_id="local-order-1",
                client_order_id=client_order_id,
                side="buy",
                order_type="market",
                size=Decimal("0.1"),
                status="submitted",
                created_at=now,
                updated_at=now,
            )
        )
    repo.save_snapshot(account_id="okx_sub_main", store=store)


def _seed_instrument(repo: InstrumentRepository) -> None:
    repo.upsert_many(
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


def _parser():
    return build_parser()


def _assert_contains(output: str, expected: str) -> None:
    if expected not in output:
        raise RuntimeError(f"expected {expected!r} in {output!r}")


class FakeGateway:
    def positions(self) -> dict:
        return {"data": []}

    def orders_pending(self) -> dict:
        return {"data": []}


if __name__ == "__main__":
    main()
