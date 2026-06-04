from __future__ import annotations

from app.services import AppServices


def record_runtime_event(
    services: AppServices,
    *,
    command: str,
    outcome: str,
    details: dict,
) -> None:
    if services.runtime_logger is None:
        return
    services.runtime_logger.record(command=command, outcome=outcome, details=details)
