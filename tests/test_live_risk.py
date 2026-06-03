from datetime import datetime, timezone
from decimal import Decimal

from live.risk import LiveEquityRiskGuard
from live.state import AccountBalance, LiveStateStore
from storage.live_repository import LiveStateRepository
from storage.safety_repository import EquityRiskState, SafetyRepository


def test_safety_repository_persists_equity_risk_state() -> None:
    repo = SafetyRepository("sqlite:///:memory:")
    state = EquityRiskState(
        account_id="okx_sub_main",
        currency="USDT",
        day="2024-01-01",
        daily_equity_baseline=Decimal("1000"),
        peak_equity=Decimal("1100"),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    repo.upsert_equity_risk_state(state)

    restored = repo.get_equity_risk_state(account_id="okx_sub_main", currency="USDT")
    assert restored is not None
    assert restored.daily_equity_baseline == Decimal("1000")
    assert restored.peak_equity == Decimal("1100")


def test_live_equity_risk_guard_initializes_baseline_from_current_equity() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    _save_balance(live_repo, equity=Decimal("1000"))

    result = LiveEquityRiskGuard(
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        account_id="okx_sub_main",
    ).evaluate(now=datetime(2024, 1, 1, tzinfo=timezone.utc))

    assert result.status == "allowed"
    assert result.reason == "within_equity_limits"
    assert result.daily_equity_baseline == Decimal("1000")
    assert result.peak_equity == Decimal("1000")


def test_live_equity_risk_guard_blocks_daily_loss_limit() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    safety_repo.upsert_equity_risk_state(
        EquityRiskState(
            account_id="okx_sub_main",
            currency="USDT",
            day="2024-01-01",
            daily_equity_baseline=Decimal("1000"),
            peak_equity=Decimal("1000"),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
    )
    _save_balance(live_repo, equity=Decimal("960"))

    result = LiveEquityRiskGuard(
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        account_id="okx_sub_main",
        max_daily_loss=Decimal("0.03"),
    ).evaluate(now=datetime(2024, 1, 1, 1, tzinfo=timezone.utc))

    assert result.status == "blocked"
    assert result.reason == "daily_loss_limit_reached"
    assert result.daily_loss_ratio == Decimal("0.04")


def test_live_equity_risk_guard_blocks_drawdown_limit() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    safety_repo.upsert_equity_risk_state(
        EquityRiskState(
            account_id="okx_sub_main",
            currency="USDT",
            day="2024-01-01",
            daily_equity_baseline=Decimal("1000"),
            peak_equity=Decimal("1200"),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
    )
    _save_balance(live_repo, equity=Decimal("1080"))

    result = LiveEquityRiskGuard(
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        account_id="okx_sub_main",
        max_daily_loss=Decimal("0.30"),
        max_total_drawdown=Decimal("0.08"),
    ).evaluate(now=datetime(2024, 1, 1, 1, tzinfo=timezone.utc))

    assert result.status == "blocked"
    assert result.reason == "drawdown_limit_reached"
    assert result.drawdown_ratio == Decimal("0.1")


def test_live_equity_risk_guard_blocks_missing_equity_snapshot() -> None:
    result = LiveEquityRiskGuard(
        live_state_repository=LiveStateRepository("sqlite:///:memory:"),
        safety_repository=SafetyRepository("sqlite:///:memory:"),
        account_id="okx_sub_main",
    ).evaluate(now=datetime(2024, 1, 1, tzinfo=timezone.utc))

    assert result.status == "blocked"
    assert result.reason == "missing_equity_snapshot"


def _save_balance(repo: LiveStateRepository, *, equity: Decimal) -> None:
    store = LiveStateStore()
    store.upsert_balance(AccountBalance(currency="USDT", equity=equity, available=equity))
    repo.save_snapshot(account_id="okx_sub_main", store=store)
