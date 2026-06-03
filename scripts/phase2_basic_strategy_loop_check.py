from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import AppServices, build_parser, run_command
from core.models import Candle, Instrument
from storage.repositories import CandleRepository, InstrumentRepository
from storage.trade_repository import TradeRepository


def main() -> None:
    try:
        _run_check()
    except Exception as exc:
        print(f"FAIL phase2 basic strategy loop check: {exc}")
        raise SystemExit(1) from exc
    print("PASS phase2 basic strategy loop check")


def _run_check() -> None:
    for symbol in ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]:
        _run_symbol_check(symbol)


def _run_symbol_check(symbol: str) -> None:
    candle_repo = CandleRepository("sqlite:///:memory:")
    instrument_repo = InstrumentRepository("sqlite:///:memory:")
    trade_repo = TradeRepository("sqlite:///:memory:")
    timeframe = "15m"
    _seed_instrument(instrument_repo, symbol)
    candle_repo.upsert_many(_ma_crossover_candles(symbol, timeframe))

    services = AppServices(
        gateway=object(),
        candle_repository=candle_repo,
        instrument_repository=instrument_repo,
        trade_repository=trade_repo,
    )
    args = build_parser().parse_args(
        ["sim-run", "--symbol", symbol, "--timeframe", timeframe, "--strategy", "ma-crossover"]
    )
    output = run_command(args, services)
    _assert_loop_result(output, trade_repo, symbol)


def _seed_instrument(repo: InstrumentRepository, symbol: str) -> None:
    repo.upsert_many(
        [
            Instrument(
                symbol=symbol,
                inst_type="SWAP",
                tick_size=Decimal("0.5"),
                lot_size=Decimal("0.03"),
                min_size=Decimal("0.03"),
                state="live",
            )
        ]
    )


def _ma_crossover_candles(symbol: str, timeframe: str) -> list[Candle]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    closes = [Decimal("100") for _ in range(28)] + [Decimal("101"), Decimal("102")]
    return [
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=start + timedelta(minutes=15 * index),
            open=close,
            high=close + Decimal("1"),
            low=close - Decimal("1"),
            close=close,
            volume=Decimal("100"),
            confirmed=True,
        )
        for index, close in enumerate(closes)
    ]


def _assert_loop_result(output: str, trade_repo: TradeRepository, symbol: str) -> None:
    if "sim_run" not in output or f"symbol={symbol}" not in output or "strategy=ma-crossover" not in output:
        raise RuntimeError(f"unexpected sim output: {output}")
    if "persisted=true" not in output:
        raise RuntimeError(f"simulation did not persist: {output}")
    if not trade_repo.list_fills("cli-sim"):
        raise RuntimeError("simulation produced no fills")
    if len(trade_repo.list_positions("cli-sim")) != 1:
        raise RuntimeError("simulation did not persist one open position")
    if not trade_repo.list_journal("cli-sim"):
        raise RuntimeError("simulation produced no journal events")


if __name__ == "__main__":
    main()
