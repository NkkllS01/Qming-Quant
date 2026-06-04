import json
from pathlib import Path

from app.run_log import RuntimeEventLogger


def test_runtime_event_logger_tails_recent_events() -> None:
    path = Path("test-runtime-events.jsonl")
    logger = RuntimeEventLogger(path)
    logger.record(command="one", outcome="completed")
    logger.record(command="two", outcome="blocked", details={"reason": "risk"})

    events = logger.tail(limit=1)

    assert len(events) == 1
    assert events[0]["command"] == "two"
    assert events[0]["details"] == {"reason": "risk"}


def test_runtime_event_logger_returns_empty_tail_for_missing_log() -> None:
    logger = RuntimeEventLogger(Path("missing-test-runtime-events.jsonl"))

    assert logger.tail(limit=10) == []


def test_runtime_event_logger_rejects_non_positive_tail_limit() -> None:
    logger = RuntimeEventLogger(Path("test-runtime-events.jsonl"))

    try:
        logger.tail(limit=0)
    except ValueError as exc:
        assert "limit must be greater than zero" in str(exc)
    else:
        raise AssertionError("expected invalid tail limit to be rejected")


def test_runtime_event_logger_writes_jsonl_events() -> None:
    path = Path("test-runtime-events.jsonl")
    logger = RuntimeEventLogger(path)

    logger.record(command="trading-gate", outcome="blocked", details={"reason": "manual_pause"})

    event = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["command"] == "trading-gate"
    assert event["outcome"] == "blocked"
    assert event["details"] == {"reason": "manual_pause"}
