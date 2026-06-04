from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field


class Settings(BaseModel):
    okx_api_key: str | None = None
    okx_secret_key: str | None = None
    okx_passphrase: str | None = None
    okx_base_url: str = "https://www.okx.com"
    okx_simulated_trading: bool = False
    database_url: str = "sqlite:///trade.db"
    run_log_path: str | None = "logs/qiming-events.jsonl"
    default_symbols: list[str] = Field(default_factory=lambda: ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    max_risk_per_trade: Decimal = Decimal("0.005")
    max_daily_loss: Decimal = Decimal("0.03")
    max_total_drawdown_pause: Decimal = Decimal("0.08")
    max_leverage: int = 3
    max_open_positions: int = 2
    max_mark_price_age_seconds: int = 120

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            okx_api_key=os.getenv("OKX_API_KEY"),
            okx_secret_key=os.getenv("OKX_SECRET_KEY"),
            okx_passphrase=os.getenv("OKX_PASSPHRASE"),
            okx_base_url=os.getenv("OKX_BASE_URL", "https://www.okx.com"),
            okx_simulated_trading=_env_bool("OKX_SIMULATED_TRADING", False),
            database_url=os.getenv("DATABASE_URL", "sqlite:///trade.db"),
            run_log_path=_env_optional_string("RUN_LOG_PATH", "logs/qiming-events.jsonl"),
            default_symbols=_env_symbols("DEFAULT_SYMBOLS", ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]),
            max_risk_per_trade=_env_decimal("MAX_RISK_PER_TRADE", Decimal("0.005")),
            max_daily_loss=_env_decimal("MAX_DAILY_LOSS", Decimal("0.03")),
            max_total_drawdown_pause=_env_decimal("MAX_TOTAL_DRAWDOWN_PAUSE", Decimal("0.08")),
            max_leverage=_env_int("MAX_LEVERAGE", 3),
            max_open_positions=_env_int("MAX_OPEN_POSITIONS", 2),
            max_mark_price_age_seconds=_env_int("MAX_MARK_PRICE_AGE_SECONDS", 120),
        )


def _env_symbols(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return list(default)
    symbols = [symbol.strip() for symbol in value.split(",") if symbol.strip()]
    if not symbols:
        raise ValueError(f"{name} must contain at least one symbol")
    return symbols


def _env_optional_string(name: str, default: str | None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    stripped = value.strip()
    return stripped or None


def _env_decimal(name: str, default: Decimal) -> Decimal:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a valid decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{name} must be a non-negative finite decimal")
    return parsed


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return parsed
