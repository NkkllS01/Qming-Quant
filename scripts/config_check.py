from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Qiming Quant environment settings.")
    parser.add_argument("--require-okx-credentials", action="store_true")
    args = parser.parse_args()

    try:
        print(_run_check(require_okx_credentials=args.require_okx_credentials))
    except Exception as exc:
        print(f"FAIL config check: {exc}")
        raise SystemExit(1) from exc


def _run_check(*, require_okx_credentials: bool = False) -> str:
    settings = Settings.from_env()
    missing = _missing_okx_credentials(settings)
    if require_okx_credentials and missing:
        raise RuntimeError("missing required environment variables: " + ", ".join(missing))

    credentials_status = "present" if not missing else "missing"
    symbols = ",".join(settings.default_symbols)
    simulated = str(settings.okx_simulated_trading).lower()
    runtime_log = "disabled" if settings.run_log_path is None else "configured"
    return (
        "PASS config check "
        f"okx_credentials={credentials_status} "
        f"simulated_trading={simulated} "
        "database=configured "
        f"default_symbols={symbols} "
        f"runtime_log={runtime_log}"
    )


def _missing_okx_credentials(settings: Settings) -> list[str]:
    missing = []
    if not settings.okx_api_key:
        missing.append("OKX_API_KEY")
    if not settings.okx_secret_key:
        missing.append("OKX_SECRET_KEY")
    if not settings.okx_passphrase:
        missing.append("OKX_PASSPHRASE")
    return missing


if __name__ == "__main__":
    main()
