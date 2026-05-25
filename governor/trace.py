"""Append-only trace.jsonl event logging."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from governor.redaction import redact
from governor.utils import utc_now_iso


@dataclass
class TraceEvent:
    run_id: str
    event_id: str
    ts: str
    phase: str
    actor: str
    action: str
    input_ref: str | None
    output_ref: str | None
    status: str
    reason: str | None = None

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class TraceLogger:
    def __init__(
        self,
        run_dir: Path,
        run_id: str,
        *,
        trace_filename: str = "trace.jsonl",
    ) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self.path = run_dir / trace_filename

    def append(
        self,
        *,
        phase: str,
        actor: str,
        action: str,
        status: str = "ok",
        input_ref: str | None = None,
        output_ref: str | None = None,
        reason: str | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            run_id=self.run_id,
            event_id=str(uuid.uuid4()),
            ts=utc_now_iso(),
            phase=phase,
            actor=actor,
            action=action,
            input_ref=input_ref,
            output_ref=output_ref,
            status=status,
            reason=redact(reason) if reason else None,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(event.to_json_line() + "\n")
        return event

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events
