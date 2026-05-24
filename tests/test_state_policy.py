"""Strict state preconditions for record, dispatch, gate, and report."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

from governor.cli import main
from governor.dispatch import build_runner_spec, execute_dispatch, preview_dispatch
from governor.models import RunState
from governor.report import generate_reports
from governor.run_store import RunStore


def test_validator_record_before_executor_fails_no_artifact():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Policy record")
        with pytest.raises(ValueError, match="Invalid transition"):
            store.record_output(meta.run_id, "validator", text="Verdict: PASS\n")
        assert not (repo / ".governor" / "runs" / meta.run_id / "06_validator_output.md").exists()


def test_validator_dispatch_before_executor_fails_no_artifact():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Policy dispatch")
        spec = build_runner_spec("echo", None)
        with pytest.raises(ValueError, match="Invalid transition"):
            execute_dispatch(
                store, meta.run_id, "validator", spec, 300, replace=False, repo_path=str(repo)
            )
        assert not (repo / ".governor" / "runs" / meta.run_id / "06_validator_output.md").exists()


def test_gate_before_executor_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Gate early")
        with pytest.raises(ValueError, match="Invalid transition"):
            store.update_state(meta.run_id, "gate")


def test_report_before_executor_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Report early")
        with pytest.raises(ValueError, match="Invalid transition"):
            generate_reports(store, meta.run_id)


def test_preview_warns_when_output_exists():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Preview warn")
        spec = build_runner_spec("echo", None)
        execute_dispatch(
            store, meta.run_id, "executor", spec, 300, replace=False, repo_path=str(repo)
        )
        preview = preview_dispatch(
            store, meta.run_id, "executor", spec, 300, replace=False
        )
        assert any("Existing output" in w for w in preview.warnings)


def test_preview_with_existing_output_cli_returns_zero():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        main(["init", "--task", "Prev warn", "--repo-path", str(repo)])
        _, meta = RunStore(repo).get_run(None)
        spec = build_runner_spec("echo", None)
        execute_dispatch(
            RunStore(repo), meta.run_id, "executor", spec, 300, replace=False, repo_path=str(repo)
        )
        rc = main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "executor",
                "--runner",
                "echo",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0


def test_execute_with_existing_output_no_replace_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Exec replace")
        spec = build_runner_spec("echo", None)
        execute_dispatch(
            store, meta.run_id, "executor", spec, 300, replace=False, repo_path=str(repo)
        )
        with pytest.raises(FileExistsError):
            execute_dispatch(
                store, meta.run_id, "executor", spec, 300, replace=False, repo_path=str(repo)
            )


def test_nonzero_dispatch_writes_failed_not_canonical():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Fail dispatch")
        fail_script = repo / "exit1.py"
        fail_script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        spec = build_runner_spec("command", [sys.executable, str(fail_script)])
        out, result = execute_dispatch(
            store, meta.run_id, "executor", spec, 30, replace=False, repo_path=str(repo)
        )
        assert result.exit_code == 1
        assert out.name == "05_executor_output.failed.md"
        assert "**Dispatch status:** FAILED" in out.read_text()
        assert not (repo / ".governor" / "runs" / meta.run_id / "05_executor_output.md").exists()
        _, updated = store.get_run(meta.run_id)
        assert updated.state == RunState.EXECUTOR_PROMPT_READY.value


def test_nonzero_dispatch_accept_failed_transitions():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Accept fail")
        fail_script = repo / "exit1.py"
        fail_script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        spec = build_runner_spec("command", [sys.executable, str(fail_script)])
        out, result = execute_dispatch(
            store,
            meta.run_id,
            "executor",
            spec,
            30,
            replace=False,
            repo_path=str(repo),
            accept_failed_output=True,
        )
        assert result.exit_code == 1
        assert out.name == "05_executor_output.md"
        _, updated = store.get_run(meta.run_id)
        assert updated.state == RunState.EXECUTOR_OUTPUT_RECORDED.value


def test_nonzero_trace_status_fail():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Trace fail")
        fail_script = repo / "exit1.py"
        fail_script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        spec = build_runner_spec("command", [sys.executable, str(fail_script)])
        execute_dispatch(
            store, meta.run_id, "executor", spec, 30, replace=False, repo_path=str(repo)
        )
        events = [json.loads(l) for l in (run_dir / "trace.jsonl").read_text().splitlines() if l.strip()]
        dispatch_exec = [e for e in events if e.get("action") == "dispatch_executor"][-1]
        assert dispatch_exec["status"] == "fail"
