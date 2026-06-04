from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.serialization import json_ready


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
            "details": json_ready(details or {}),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    def tail(self, *, limit: int) -> list[dict[str, Any]]:
        if not self.enabled or not self.path.exists():
            return []
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()]
