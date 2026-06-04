from __future__ import annotations

import argparse
import json

from app.commands.live_ops import evaluate_cli_trading_gate
from app.commands.runtime import record_runtime_event
from app.services import AppServices


def register(subparsers: argparse._SubParsersAction) -> None:
    operator_status = subparsers.add_parser("operator-status", help="Show operator safety status summary")
    operator_status.add_argument("--account-id", default="okx_sub_main")
    operator_status.add_argument("--skip-gate", action="store_true")
    operator_status.add_argument("--include-gate", action="store_true")
    operator_status.set_defaults(handler=handle_operator_status)

    emergency_pause = subparsers.add_parser("emergency-pause", help="Manually block live trading")
    emergency_pause.add_argument("--account-id", default="okx_sub_main")
    emergency_pause.add_argument("--reason", default="manual_emergency_pause")
    emergency_pause.set_defaults(handler=handle_emergency_pause)

    emergency_resume = subparsers.add_parser("emergency-resume", help="Clear manual live trading pause")
    emergency_resume.add_argument("--account-id", default="okx_sub_main")
    emergency_resume.add_argument("--reason", default="manual_resume")
    emergency_resume.set_defaults(handler=handle_emergency_resume)

    run_log_tail = subparsers.add_parser("run-log-tail", help="Print recent runtime audit events")
    run_log_tail.add_argument("--limit", type=int, default=20)
    run_log_tail.set_defaults(handler=handle_run_log_tail)


def handle_emergency_pause(args: argparse.Namespace, services: AppServices) -> str:
    if services.safety_repository is None:
        raise RuntimeError("Safety repository is not configured")
    state = services.safety_repository.set_pause(account_id=args.account_id, paused=True, reason=args.reason)
    output = (
        f"emergency_pause account_id={state.account_id} paused={str(state.paused).lower()} "
        f"reason={state.reason} trading_allowed=false"
    )
    record_runtime_event(
        services,
        command=args.command,
        outcome="paused",
        details={"account_id": state.account_id, "reason": state.reason},
    )
    return output


def handle_emergency_resume(args: argparse.Namespace, services: AppServices) -> str:
    if services.safety_repository is None:
        raise RuntimeError("Safety repository is not configured")
    state = services.safety_repository.set_pause(account_id=args.account_id, paused=False, reason=args.reason)
    output = (
        f"emergency_resume account_id={state.account_id} paused={str(state.paused).lower()} "
        f"reason={state.reason}"
    )
    record_runtime_event(
        services,
        command=args.command,
        outcome="resumed",
        details={"account_id": state.account_id, "reason": state.reason},
    )
    return output


def handle_run_log_tail(args: argparse.Namespace, services: AppServices) -> str:
    if services.runtime_logger is None:
        return "run_log_tail status=disabled"
    events = services.runtime_logger.tail(limit=args.limit)
    if not events:
        return "run_log_tail status=empty"
    return "\n".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) for event in events)


def handle_operator_status(args: argparse.Namespace, services: AppServices) -> str:
    if services.safety_repository is None:
        raise RuntimeError("Safety repository is not configured")
    pause_state = services.safety_repository.get_pause(account_id=args.account_id)
    gate_result = None
    if args.include_gate and not args.skip_gate:
        gate_result = evaluate_cli_trading_gate(
            services,
            account_id=args.account_id,
            symbols=services.default_symbols or ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
        )
    latest_events = services.runtime_logger.tail(limit=1) if services.runtime_logger is not None else []
    latest_event = latest_events[-1] if latest_events else None
    gate_status = gate_result.status if gate_result is not None else "skipped"
    gate_reason = gate_result.reason if gate_result is not None else "skipped"
    trading_allowed = gate_result.trading_allowed if gate_result is not None else False
    last_event_status = latest_event_status(services, latest_event)
    last_event_command = latest_event["command"] if latest_event is not None else "none"
    last_event_outcome = latest_event["outcome"] if latest_event is not None else "none"
    last_event_timestamp = latest_event["timestamp"] if latest_event is not None else "none"
    return (
        f"operator_status account_id={args.account_id} "
        f"manual_paused={str(pause_state.paused).lower()} "
        f"pause_reason={pause_state.reason} "
        f"pause_updated_at={pause_state.updated_at.isoformat()} "
        f"gate_status={gate_status} gate_reason={gate_reason} "
        f"trading_allowed={str(trading_allowed).lower()} "
        f"last_event={last_event_status} "
        f"last_event_command={last_event_command} "
        f"last_event_outcome={last_event_outcome} "
        f"last_event_timestamp={last_event_timestamp}"
    )


def latest_event_status(services: AppServices, latest_event: dict | None) -> str:
    if services.runtime_logger is None:
        return "disabled"
    if latest_event is None:
        return "empty"
    return "available"
