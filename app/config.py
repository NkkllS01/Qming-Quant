from __future__ import annotations

import os
from decimal import Decimal

from pydantic import BaseModel


class Settings(BaseModel):
    okx_api_key: str | None = None
    okx_secret_key: str | None = None
    okx_passphrase: str | None = None
    database_url: str = "sqlite:///trade.db"
    default_symbols: list[str] = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    max_risk_per_trade: Decimal = Decimal("0.005")
    max_daily_loss: Decimal = Decimal("0.03")
    max_total_drawdown_pause: Decimal = Decimal("0.08")
    max_leverage: int = 3
    max_open_positions: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            okx_api_key=os.getenv("OKX_API_KEY"),
            okx_secret_key=os.getenv("OKX_SECRET_KEY"),
            okx_passphrase=os.getenv("OKX_PASSPHRASE"),
            database_url=os.getenv("DATABASE_URL", "sqlite:///trade.db"),
        )

