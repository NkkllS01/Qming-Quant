from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import AppServices, build_parser, run_command
from app.run_log import RuntimeEventLogger
from storage.repositories import CandleRepository
from storage.safety_repository import SafetyRepository


def main() -> None:
    try:
        _run_check()
    except Exception as exc:
        print(f"FAIL phase4 monitoring check: {exc}")
        raise SystemExit(1) from exc
    print("PASS phase4 monitoring check")


def _run_check() -> None:
    services = _services()
    _assert_contains(_command(services, ["operator-status", "--skip-gate"]), "manual_paused=false")
    readiness = _command(services, ["prelive-readiness"])
    _assert_contains(readiness, "prelive_readiness status=blocked")
    _assert_contains(readiness, "runtime_log=configured")
    _assert_contains(readiness, "manual_paused=false")
    _assert_contains(_command(services, ["emergency-pause", "--reason", "phase4_smoke_pause"]), "paused=true")
    _assert_contains(_command(services, ["operator-status", "--skip-gate"]), "manual_paused=true")
    pause_event = _tail_json(services, limit=1)[0]
    if pause_event["command"] != "emergency-pause":
        raise RuntimeError(f"unexpected pause event: {pause_event}")
    _assert_contains(_command(services, ["emergency-resume", "--reason", "phase4_smoke_resume"]), "paused=false")
    events = _tail_json(services, limit=2)
    if [event["command"] for event in events] != ["emergency-pause", "emergency-resume"]:
        raise RuntimeError(f"unexpected runtime events: {events}")


def _services() -> AppServices:
    database_url = "sqlite:///:memory:"
    safety_repo = SafetyRepository(database_url)
    return AppServices(
        gateway=object(),
        candle_repository=CandleRepository(database_url),
        safety_repository=safety_repo,
        runtime_logger=RuntimeEventLogger(Path(f"test-runtime-events-phase4-{os.getpid()}.jsonl")),
        default_symbols=["BTC-USDT-SWAP"],
    )


def _command(services: AppServices, argv: list[str]) -> str:
    return run_command(build_parser().parse_args(argv), services)


def _tail_json(services: AppServices, *, limit: int) -> list[dict]:
    return [json.loads(line) for line in _command(services, ["run-log-tail", "--limit", str(limit)]).splitlines()]


def _assert_contains(output: str, expected: str) -> None:
    if expected not in output:
        raise RuntimeError(f"expected {expected!r} in {output!r}")


if __name__ == "__main__":
    main()
