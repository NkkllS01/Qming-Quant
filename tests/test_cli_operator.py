import json
from pathlib import Path

from tests.cli_fakes import FakeGateway, add_usdt_balance
from app.main import AppServices, build_parser, run_command
from app.run_log import RuntimeEventLogger
from storage.live_repository import LiveStateRepository
from storage.repositories import (
    CandleRepository,
)
from storage.safety_repository import SafetyRepository
from tests.fakes import (
    live_store_with_position_and_order,
)






def test_run_emergency_pause_and_resume_commands_persist_manual_state() -> None:
    safety_repo = SafetyRepository("sqlite:///:memory:")
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        safety_repository=safety_repo,
    )

    pause_output = run_command(
        build_parser().parse_args(["emergency-pause", "--reason", "operator_stop"]),
        services,
    )
    resume_output = run_command(
        build_parser().parse_args(["emergency-resume", "--reason", "operator_resume"]),
        services,
    )

    assert "emergency_pause account_id=okx_sub_main paused=true" in pause_output
    assert "trading_allowed=false" in pause_output
    assert "emergency_resume account_id=okx_sub_main paused=false" in resume_output
    assert safety_repo.get_pause(account_id="okx_sub_main").paused is False


def test_run_emergency_pause_records_runtime_event() -> None:
    log_path = Path("test-runtime-events.jsonl")
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        safety_repository=SafetyRepository("sqlite:///:memory:"),
        runtime_logger=RuntimeEventLogger(log_path),
    )

    run_command(
        build_parser().parse_args(["emergency-pause", "--reason", "operator_stop"]),
        services,
    )

    event = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["system"] == "Qiming Quant"
    assert event["component"] == "cli"
    assert event["command"] == "emergency-pause"
    assert event["outcome"] == "paused"
    assert event["details"] == {
        "account_id": "okx_sub_main",
        "reason": "operator_stop",
    }


def test_run_log_tail_returns_recent_runtime_events() -> None:
    log_path = Path("test-runtime-events.jsonl")
    logger = RuntimeEventLogger(log_path)
    logger.record(command="first", outcome="completed")
    logger.record(command="second", outcome="blocked", details={"reason": "test"})
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        runtime_logger=logger,
    )

    output = run_command(build_parser().parse_args(["run-log-tail", "--limit", "1"]), services)

    event = json.loads(output)
    assert event["command"] == "second"
    assert event["outcome"] == "blocked"
    assert event["details"] == {"reason": "test"}


def test_run_log_tail_reports_disabled_when_logger_is_not_configured() -> None:
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        runtime_logger=None,
    )

    output = run_command(build_parser().parse_args(["run-log-tail"]), services)

    assert output == "run_log_tail status=disabled"


def test_operator_status_reports_pause_state_and_latest_event_without_gate() -> None:
    log_path = Path("test-runtime-events.jsonl")
    logger = RuntimeEventLogger(log_path)
    logger.record(command="trading-gate", outcome="blocked", details={"reason": "manual_pause"})
    safety_repo = SafetyRepository("sqlite:///:memory:")
    safety_repo.set_pause(account_id="okx_sub_main", paused=True, reason="operator_stop")
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        safety_repository=safety_repo,
        runtime_logger=logger,
    )

    output = run_command(build_parser().parse_args(["operator-status", "--skip-gate"]), services)

    assert "operator_status account_id=okx_sub_main" in output
    assert "manual_paused=true" in output
    assert "pause_reason=operator_stop" in output
    assert "pause_updated_at=" in output
    assert "gate_status=skipped" in output
    assert "gate_reason=skipped" in output
    assert "trading_allowed=false" in output
    assert "last_event=available" in output
    assert "last_event_command=trading-gate" in output
    assert "last_event_outcome=blocked" in output
    assert "last_event_timestamp=" in output


def test_operator_status_is_local_only_by_default() -> None:
    safety_repo = SafetyRepository("sqlite:///:memory:")
    live_repo = LiveStateRepository("sqlite:///:memory:")
    store = live_store_with_position_and_order(order_id="okx-1", direction="long", size="0.1")
    add_usdt_balance(store)
    live_repo.save_snapshot(account_id="okx_sub_main", store=store)
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=live_repo,
        safety_repository=safety_repo,
        runtime_logger=None,
    )

    output = run_command(build_parser().parse_args(["operator-status"]), services)

    assert "manual_paused=false" in output
    assert "gate_status=skipped" in output
    assert "trading_allowed=false" in output
    assert safety_repo.get_equity_risk_state(account_id="okx_sub_main", currency="USDT") is None


def test_operator_status_evaluates_trading_gate_when_included() -> None:
    safety_repo = SafetyRepository("sqlite:///:memory:")
    safety_repo.set_pause(account_id="okx_sub_main", paused=True, reason="manual")
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        live_state_repository=LiveStateRepository("sqlite:///:memory:"),
        safety_repository=safety_repo,
        runtime_logger=None,
    )

    output = run_command(build_parser().parse_args(["operator-status", "--include-gate"]), services)

    assert "manual_paused=true" in output
    assert "pause_reason=manual" in output
    assert "gate_status=blocked" in output
    assert "gate_reason=manual_pause" in output
    assert "trading_allowed=false" in output
    assert "last_event=disabled" in output
    assert "last_event_command=none" in output


def test_operator_status_reports_empty_runtime_log() -> None:
    services = AppServices(
        gateway=FakeGateway(),
        candle_repository=CandleRepository("sqlite:///:memory:"),
        safety_repository=SafetyRepository("sqlite:///:memory:"),
        runtime_logger=RuntimeEventLogger(Path("missing-test-runtime-events.jsonl")),
    )

    output = run_command(build_parser().parse_args(["operator-status", "--skip-gate"]), services)

    assert "last_event=empty" in output
    assert "last_event_command=none" in output
