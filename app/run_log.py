from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass
class RuntimeEventLogger:
    path: Path
    system: str = "Qiming Quant"
    component: str = "cli"
    enabled: bool = True
    _sequence: int = field(default=0, init=False)

    def record(self, *, command: str, outcome: str, details: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        self._sequence += 1
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sequence": self._sequence,
            "system": self.system,
            "component": self.component,
            "command": command,
            "outcome": outcome,
            "details": _json_ready(details or {}),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
