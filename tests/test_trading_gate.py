from datetime import datetime, timezone
from decimal import Decimal

from core.models import Position
from live.reconcile import LiveReconciliationService
from live.risk import LiveEquityRiskGuard
from live.state import AccountBalance, LiveStateStore
from live.trading_gate import TradingGateService
from storage.live_repository import LiveStateRepository
from storage.safety_repository import EquityRiskState, SafetyRepository


def test_safety_repository_defaults_to_not_paused_and_persists_pause_state() -> None:
    repo = SafetyRepository("sqlite:///:memory:")

    initial = repo.get_pause(account_id="okx_sub_main")
    paused = repo.set_pause(account_id="okx_sub_main", paused=True, reason="manual")
    restored = repo.get_pause(account_id="okx_sub_main")

    assert initial.paused is False
    assert initial.reason == "not_paused"
    assert paused.paused is True
    assert restored.paused is True
    assert restored.reason == "manual"


def test_trading_gate_blocks_when_manually_paused_without_reconciliation() -> None:
    safety_repo = SafetyRepository("sqlite:///:memory:")
    safety_repo.set_pause(account_id="okx_sub_main", paused=True, reason="maintenance")
    gate = TradingGateService(
        reconciliation=FailingReconciliation(),
        safety_repository=safety_repo,
        account_id="okx_sub_main",
    )

    result = gate.evaluate()

    assert result.status == "blocked"
    assert result.reason == "manual_pause"
    assert result.trading_allowed is False
    assert result.reconciliation is None


def test_trading_gate_allows_when_not_paused_and_reconciliation_is_clean() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    _save_local_position(live_repo, size="0.1", direction="long")
    reconciliation = LiveReconciliationService(
        gateway=FakeGateway(positions=[{"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0.1"}]),
        repository=live_repo,
        account_id="okx_sub_main",
    )

    result = TradingGateService(
        reconciliation=reconciliation,
        safety_repository=safety_repo,
        account_id="okx_sub_main",
    ).evaluate()

    assert result.status == "allowed"
    assert result.reason == "all_checks_passed"
    assert result.trading_allowed is True


def test_trading_gate_blocks_when_reconciliation_is_not_clean() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    _save_local_position(live_repo, size="0.1", direction="long")
    reconciliation = LiveReconciliationService(
        gateway=FakeGateway(positions=[{"instId": "BTC-USDT-SWAP", "posSide": "short", "pos": "-0.2"}]),
        repository=live_repo,
        account_id="okx_sub_main",
    )

    result = TradingGateService(
        reconciliation=reconciliation,
        safety_repository=safety_repo,
        account_id="okx_sub_main",
    ).evaluate()

    assert result.status == "blocked"
    assert result.reason == "reconciliation_blocked"
    assert result.trading_allowed is False
    assert result.reconciliation is not None
    assert len(result.reconciliation.positions_issues) == 2


def test_trading_gate_blocks_on_equity_risk_before_reconciliation() -> None:
    live_repo = LiveStateRepository("sqlite:///:memory:")
    safety_repo = SafetyRepository("sqlite:///:memory:")
    _save_balance(live_repo, equity="960")
    safety_repo.upsert_equity_risk_state(
        EquityRiskState(
            account_id="okx_sub_main",
            currency="USDT",
            day=datetime.now(timezone.utc).date().isoformat(),
            daily_equity_baseline=Decimal("1000"),
            peak_equity=Decimal("1000"),
            updated_at=datetime.now(timezone.utc),
        )
    )
    gate = TradingGateService(
        reconciliation=FailingReconciliation(),
        safety_repository=safety_repo,
        account_id="okx_sub_main",
        equity_risk_guard=LiveEquityRiskGuard(
            live_state_repository=live_repo,
            safety_repository=safety_repo,
            account_id="okx_sub_main",
            max_daily_loss=Decimal("0.03"),
        ),
    )

    result = gate.evaluate()

    assert result.status == "blocked"
    assert result.reason == "daily_loss_limit_reached"
    assert result.equity_risk is not None
    assert result.reconciliation is None


class FakeGateway:
    def __init__(self, *, positions: list[dict]) -> None:
        self._positions = positions

    def positions(self) -> dict:
        return {"data": self._positions}

    def orders_pending(self) -> dict:
        return {"data": []}


class FailingReconciliation:
    def run(self):
        raise AssertionError("reconciliation should not run while manually paused")


def _save_local_position(repo: LiveStateRepository, *, size: str, direction: str) -> None:
    store = LiveStateStore()
    store.upsert_position(
        Position(
            account_id="okx_sub_main",
            symbol="BTC-USDT-SWAP",
            direction=direction,
            size=Decimal(size),
            entry_price=Decimal("70000"),
            mark_price=Decimal("70100"),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
    )
    repo.save_snapshot(account_id="okx_sub_main", store=store)


def _save_balance(repo: LiveStateRepository, *, equity: str) -> None:
    store = LiveStateStore()
    store.upsert_balance(
        AccountBalance(
            currency="USDT",
            equity=Decimal(equity),
            available=Decimal(equity),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
    )
    repo.save_snapshot(account_id="okx_sub_main", store=store)
