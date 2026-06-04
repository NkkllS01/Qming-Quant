from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.config import Settings
from app.run_log import RuntimeEventLogger
from exchanges.okx.gateway import OKXGateway
from exchanges.okx.rest import OKXRestClient
from exchanges.okx.websocket import OKXWebSocketClient, OKXWebSocketConfig, WebsocketsConnector
from storage.live_repository import LiveStateRepository
from storage.repositories import (
    CandleRepository,
    FundingRateRepository,
    IndexPriceRepository,
    InstrumentRepository,
    MarkPriceRepository,
)
from storage.safety_repository import SafetyRepository
from storage.trade_repository import TradeRepository


@dataclass
class AppServices:
    gateway: object
    candle_repository: CandleRepository
    instrument_repository: InstrumentRepository | None = None
    funding_rate_repository: FundingRateRepository | None = None
    mark_price_repository: MarkPriceRepository | None = None
    index_price_repository: IndexPriceRepository | None = None
    trade_repository: TradeRepository | None = None
    websocket_connector: object | None = None
    live_state_repository: LiveStateRepository | None = None
    safety_repository: SafetyRepository | None = None
    runtime_logger: RuntimeEventLogger | None = None
    max_daily_loss: Decimal = Decimal("0.03")
    max_total_drawdown_pause: Decimal = Decimal("0.08")
    default_symbols: list[str] | None = None
    max_mark_price_age_seconds: int = 120
    max_risk_per_trade: Decimal = Decimal("0.005")
    max_open_positions: int = 2


def build_services(settings: Settings | None = None) -> AppServices:
    settings = settings or Settings.from_env()
    rest = OKXRestClient(
        api_key=settings.okx_api_key,
        secret_key=settings.okx_secret_key,
        passphrase=settings.okx_passphrase,
        base_url=settings.okx_base_url,
        simulated_trading=settings.okx_simulated_trading,
    )
    public_ws = OKXWebSocketClient(OKXWebSocketConfig())
    private_ws = OKXWebSocketClient(
        OKXWebSocketConfig(
            api_key=settings.okx_api_key,
            secret_key=settings.okx_secret_key,
            passphrase=settings.okx_passphrase,
        )
    )
    return AppServices(
        gateway=OKXGateway(rest, public_ws=public_ws, private_ws=private_ws),
        candle_repository=CandleRepository(settings.database_url),
        instrument_repository=InstrumentRepository(settings.database_url),
        funding_rate_repository=FundingRateRepository(settings.database_url),
        mark_price_repository=MarkPriceRepository(settings.database_url),
        index_price_repository=IndexPriceRepository(settings.database_url),
        trade_repository=TradeRepository(settings.database_url),
        websocket_connector=WebsocketsConnector(),
        live_state_repository=LiveStateRepository(settings.database_url),
        safety_repository=SafetyRepository(settings.database_url),
        runtime_logger=(
            RuntimeEventLogger(Path(settings.run_log_path))
            if settings.run_log_path is not None
            else None
        ),
        max_daily_loss=settings.max_daily_loss,
        max_total_drawdown_pause=settings.max_total_drawdown_pause,
        max_risk_per_trade=settings.max_risk_per_trade,
        max_open_positions=settings.max_open_positions,
        default_symbols=settings.default_symbols,
        max_mark_price_age_seconds=settings.max_mark_price_age_seconds,
    )
