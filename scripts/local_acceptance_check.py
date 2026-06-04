from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.data_quality_check import _run_check as run_data_quality_check
from scripts.phase2_basic_strategy_loop_check import _run_check as run_phase2_check
from scripts.phase3_risk_controls_check import _run_check as run_phase3_check
from scripts.phase4_monitoring_check import _run_check as run_phase4_check
from scripts.prelive_order_check import _run_check as run_prelive_order_check


CHECKS = [
    ("data_quality", run_data_quality_check),
    ("phase2_strategy_loop", run_phase2_check),
    ("phase3_risk_controls", run_phase3_check),
    ("phase4_monitoring", run_phase4_check),
    ("prelive_order_check", run_prelive_order_check),
]


def main() -> None:
    try:
        _run_check()
    except Exception as exc:
        print(f"FAIL local acceptance check: {exc}")
        raise SystemExit(1) from exc
    print("PASS local acceptance check")


def _run_check() -> None:
    for name, check in CHECKS:
        print(f"RUN {name}")
        try:
            check()
        except Exception as exc:
            print(f"FAIL {name}: {exc}")
            raise
        print(f"PASS {name}")


if __name__ == "__main__":
    main()
