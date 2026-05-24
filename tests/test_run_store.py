"""Tests for run folder creation and trace logging."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governor.models import RunState
from governor.run_store import RunStore
from governor.trace import TraceLogger


def test_create_run_writes_artifacts_and_state():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Centralize retry policy")

        assert meta.state == RunState.EXECUTOR_PROMPT_READY.value
        assert (run_dir / "00_task_intake.md").exists()
        assert (run_dir / "03_executor_prompt.md").exists()
        assert (run_dir / "04_validator_prompt.md").exists()
        assert (run_dir / "trace.jsonl").exists()
        assert (run_dir / "run_state.json").exists()

        state = json.loads((run_dir / "run_state.json").read_text())
        assert state["task"] == "Centralize retry policy"
        assert state["run_id"] in run_dir.name


def test_trace_append():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Trace test")
        trace = TraceLogger(run_dir, meta.run_id)
        trace.append(phase="test", actor="pytest", action="ping", status="ok")
        events = trace.read_all()
        assert len(events) >= 2  # init + ping
        assert events[-1]["action"] == "ping"
        assert events[-1]["run_id"] == meta.run_id


def test_record_executor_updates_state():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Record test")
        out = store.record_output(meta.run_id, "executor", text="## Done\n- file.py")
        assert out.name == "05_executor_output.md"
        _, updated = store.get_run(meta.run_id)
        assert updated.state == RunState.EXECUTOR_OUTPUT_RECORDED.value
