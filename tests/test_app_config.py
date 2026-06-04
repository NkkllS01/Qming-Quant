from decimal import Decimal

from app.config import Settings
from app.main import build_services


def test_settings_rejects_invalid_risk_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("MAX_DAILY_LOSS", "not-a-decimal")

    try:
        Settings.from_env()
    except ValueError as exc:
        assert "MAX_DAILY_LOSS must be a valid decimal" in str(exc)
    else:
        raise AssertionError("expected invalid MAX_DAILY_LOSS to be rejected")


def test_settings_rejects_empty_default_symbols(monkeypatch) -> None:
    monkeypatch.setenv("DEFAULT_SYMBOLS", ", ,")

    try:
        Settings.from_env()
    except ValueError as exc:
        assert "DEFAULT_SYMBOLS must contain at least one symbol" in str(exc)
    else:
        raise AssertionError("expected empty DEFAULT_SYMBOLS to be rejected")


def test_settings_reads_okx_credentials_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("OKX_API_KEY", "key")
    monkeypatch.setenv("OKX_SECRET_KEY", "secret")
    monkeypatch.setenv("OKX_PASSPHRASE", "passphrase")
    monkeypatch.setenv("OKX_BASE_URL", "https://www.okx.com")
    monkeypatch.setenv("OKX_SIMULATED_TRADING", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///trade.db")
    monkeypatch.setenv("RUN_LOG_PATH", "logs/test-events.jsonl")
    monkeypatch.setenv("DEFAULT_SYMBOLS", "BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP")
    monkeypatch.setenv("MAX_RISK_PER_TRADE", "0.004")
    monkeypatch.setenv("MAX_DAILY_LOSS", "0.02")
    monkeypatch.setenv("MAX_TOTAL_DRAWDOWN_PAUSE", "0.06")
    monkeypatch.setenv("MAX_LEVERAGE", "2")
    monkeypatch.setenv("MAX_OPEN_POSITIONS", "1")
    monkeypatch.setenv("MAX_MARK_PRICE_AGE_SECONDS", "60")

    settings = Settings.from_env()

    assert settings.okx_api_key == "key"
    assert settings.okx_secret_key == "secret"
    assert settings.okx_passphrase == "passphrase"
    assert settings.okx_base_url == "https://www.okx.com"
    assert settings.okx_simulated_trading is True
    assert settings.database_url == "sqlite:///trade.db"
    assert settings.run_log_path == "logs/test-events.jsonl"
    assert settings.default_symbols == ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
    assert settings.max_risk_per_trade == Decimal("0.004")
    assert settings.max_daily_loss == Decimal("0.02")
    assert settings.max_total_drawdown_pause == Decimal("0.06")
    assert settings.max_leverage == 2
    assert settings.max_open_positions == 1
    assert settings.max_mark_price_age_seconds == 60


def test_build_services_passes_okx_rest_demo_settings() -> None:
    settings = Settings(
        okx_api_key="key",
        okx_secret_key="secret",
        okx_passphrase="passphrase",
        okx_base_url="https://example.test/",
        okx_simulated_trading=True,
        database_url="sqlite:///:memory:",
    )

    services = build_services(settings)

    assert services.gateway.rest.base_url == "https://example.test"
    assert services.gateway.rest.simulated_trading is True
    assert services.runtime_logger is not None


def test_settings_allows_disabling_runtime_log_path(monkeypatch) -> None:
    monkeypatch.setenv("RUN_LOG_PATH", "")

    settings = Settings.from_env()

    assert settings.run_log_path is None
