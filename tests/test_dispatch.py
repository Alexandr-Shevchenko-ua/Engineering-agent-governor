"""Tests for bounded dispatch."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

from governor.cli import main
from governor.dispatch import (
    build_runner_spec,
    execute_dispatch,
    execute_runner,
    preview_dispatch,
    run_echo,
    validate_timeout,
)
from governor.models import RunState
from governor.run_store import RunStore


def test_preview_does_not_create_output():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Dispatch preview")
        spec = build_runner_spec("echo", None)
        preview_dispatch(store, meta.run_id, "executor", spec, 300, replace=False)
        assert not (repo / ".governor" / "runs" / meta.run_id / "05_executor_output.md").exists()


def test_echo_dispatch_executor_state():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Echo exec")
        spec = build_runner_spec("echo", None)
        out, result = execute_dispatch(
            store, meta.run_id, "executor", spec, 300, replace=False, repo_path=str(repo)
        )
        assert result.exit_code == 0
        assert out.name == "05_executor_output.md"
        _, updated = store.get_run(meta.run_id)
        assert updated.state == RunState.EXECUTOR_OUTPUT_RECORDED.value
        assert "Echo dispatch" in out.read_text()


def test_echo_dispatch_validator_state():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Echo val")
        spec = build_runner_spec("echo", None)
        execute_dispatch(
            store, meta.run_id, "executor", spec, 300, replace=False, repo_path=str(repo)
        )
        execute_dispatch(
            store, meta.run_id, "validator", spec, 300, replace=False, repo_path=str(repo)
        )
        _, updated = store.get_run(meta.run_id)
        assert updated.state == RunState.VALIDATOR_OUTPUT_RECORDED.value


def test_dispatch_overwrite_protection():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Overwrite")
        spec = build_runner_spec("echo", None)
        execute_dispatch(
            store, meta.run_id, "executor", spec, 300, replace=False, repo_path=str(repo)
        )
        with pytest.raises(FileExistsError):
            execute_dispatch(
                store, meta.run_id, "executor", spec, 300, replace=False, repo_path=str(repo)
            )


def test_command_runner_requires_command():
    with pytest.raises(ValueError, match="--command"):
        build_runner_spec("command", None)


def test_execute_requires_approve_cli():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        rc = main(
            [
                "init",
                "--task",
                "No approve",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        _, meta = RunStore(repo).get_run(None)
        rc2 = main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "executor",
                "--runner",
                "echo",
                "--approve",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc2 == 0


def test_preview_without_approve_no_output_cli():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        main(["init", "--task", "Preview cli", "--repo-path", str(repo)])
        _, meta = RunStore(repo).get_run(None)
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
        assert not (
            repo / ".governor" / "runs" / meta.run_id / "05_executor_output.md"
        ).exists()


def test_timeout_validation():
    with pytest.raises(ValueError):
        validate_timeout(0)
    with pytest.raises(ValueError):
        validate_timeout(9999)


def test_cursor_runner_clear_message():
    spec = build_runner_spec("cursor", None)
    result = execute_runner(spec, "executor", "prompt", Path("."), 60)
    assert result.exit_code != 0
    assert "cursor" in result.stderr.lower() or "Cursor" in result.stderr


def test_trace_dispatch_events():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Trace dispatch")
        spec = build_runner_spec("echo", None)
        preview_dispatch(store, meta.run_id, "executor", spec, 300, replace=False)
        execute_dispatch(
            store, meta.run_id, "executor", spec, 300, replace=False, repo_path=str(repo)
        )
        events = [
            json.loads(line)
            for line in (run_dir / "trace.jsonl").read_text().splitlines()
            if line.strip()
        ]
        actions = [e["action"] for e in events]
        assert "dispatch_preview" in actions
        assert "dispatch_executor" in actions


def test_redaction_in_dispatch_output():
    secret = 'api_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"'
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Redact dispatch")
        fake = repo / "fake_agent.py"
        fake.write_text(
            "import sys\nprint(sys.stdin.read())\nprint('" + secret + "')\n",
            encoding="utf-8",
        )
        spec = build_runner_spec(
            "command", [sys.executable, str(fake)]
        )
        out, _ = execute_dispatch(
            store,
            meta.run_id,
            "executor",
            spec,
            30,
            replace=False,
            repo_path=str(repo),
        )
        body = out.read_text(encoding="utf-8")
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in body
