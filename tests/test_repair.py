"""Tests for repair prepare, dispatch, and report integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from governor.cli import main
from governor.models import RunState
from governor.repair_artifacts import repair_prompt_name, repair_output_name
from governor.run_store import RunStore


def _run_to_gates(repo: Path, run_id: str) -> None:
    store = RunStore(repo)
    from governor.dispatch import build_runner_spec, execute_dispatch

    spec = build_runner_spec("echo", None)
    execute_dispatch(
        store, run_id, "executor", spec, 300, replace=False, repo_path=str(repo)
    )
    main(["gate", "--run-id", run_id, "--repo-path", str(repo)])


def test_prepare_fails_before_executor():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Early repair")
        rc = main(
            [
                "repair",
                "prepare",
                "--run-id",
                meta.run_id,
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 1


def test_prepare_succeeds_after_gate():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Gate repair")
        _run_to_gates(repo, meta.run_id)
        rc = main(
            [
                "repair",
                "prepare",
                "--run-id",
                meta.run_id,
                "--repo-path",
                str(repo),
                "--reason",
                "Fix lint",
            ]
        )
        assert rc == 0
        run_dir = repo / ".governor" / "runs" / meta.run_id
        assert (run_dir / repair_prompt_name(1)).is_file()
        text = (run_dir / repair_prompt_name(1)).read_text()
        assert "Fix lint" in text
        assert "Gate summary" in text
        trace = (run_dir / "trace.jsonl").read_text()
        assert "repair_prepare" in trace


def test_second_prepare_creates_prompt_2():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Two repairs")
        _run_to_gates(repo, meta.run_id)
        main(["repair", "prepare", "--run-id", meta.run_id, "--repo-path", str(repo)])
        rc = main(["repair", "prepare", "--run-id", meta.run_id, "--repo-path", str(repo)])
        assert rc == 0
        run_dir = repo / ".governor" / "runs" / meta.run_id
        assert (run_dir / repair_prompt_name(2)).is_file()


def test_max_repair_guard():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Max repair")
        _run_to_gates(repo, meta.run_id)
        main(["repair", "prepare", "--run-id", meta.run_id, "--repo-path", str(repo)])
        main(["repair", "prepare", "--run-id", meta.run_id, "--repo-path", str(repo)])
        rc = main(
            [
                "repair",
                "prepare",
                "--run-id",
                meta.run_id,
                "--repo-path",
                str(repo),
                "--max-repairs",
                "2",
            ]
        )
        assert rc == 1


def test_repair_dispatch_preview_no_output():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Repair prev")
        _run_to_gates(repo, meta.run_id)
        main(["repair", "prepare", "--run-id", meta.run_id, "--repo-path", str(repo)])
        rc = main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "repair",
                "--runner",
                "echo",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        out = repo / ".governor" / "runs" / meta.run_id / repair_output_name(1)
        assert not out.exists()


def test_repair_dispatch_execute_state():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Repair exec")
        _run_to_gates(repo, meta.run_id)
        main(["repair", "prepare", "--run-id", meta.run_id, "--repo-path", str(repo)])
        rc = main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "repair",
                "--runner",
                "echo",
                "--approve",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        run_dir = repo / ".governor" / "runs" / meta.run_id
        assert (run_dir / repair_output_name(1)).is_file()
        _, updated = store.get_run(meta.run_id)
        assert updated.state == RunState.REPAIR_RECORDED.value
        assert "dispatch_repair" in (run_dir / "trace.jsonl").read_text()


def test_repair_dispatch_without_prompt_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("No prompt")
        _run_to_gates(repo, meta.run_id)
        rc = main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "repair",
                "--runner",
                "echo",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 1


def test_gate_allowed_after_repair():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Gate after")
        _run_to_gates(repo, meta.run_id)
        main(["repair", "prepare", "--run-id", meta.run_id, "--repo-path", str(repo)])
        main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "repair",
                "--runner",
                "echo",
                "--approve",
                "--repo-path",
                str(repo),
            ]
        )
        rc = main(["gate", "--run-id", meta.run_id, "--repo-path", str(repo)])
        assert rc in (0, 2)


def test_record_repair_without_prompt_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Rec no prep")
        _run_to_gates(repo, meta.run_id)
        rc = main(
            [
                "record",
                "--run-id",
                meta.run_id,
                "--role",
                "repair",
                "--text",
                "fix",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 1


def test_record_repair_after_prepare():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Rec prep")
        _run_to_gates(repo, meta.run_id)
        main(["repair", "prepare", "--run-id", meta.run_id, "--repo-path", str(repo)])
        rc = main(
            [
                "record",
                "--run-id",
                meta.run_id,
                "--role",
                "repair",
                "--text",
                "## Repair done",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0


def test_report_includes_repair_history():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("Report repair")
        _run_to_gates(repo, meta.run_id)
        main(["repair", "prepare", "--run-id", meta.run_id, "--repo-path", str(repo)])
        main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "repair",
                "--runner",
                "echo",
                "--approve",
                "--repo-path",
                str(repo),
            ]
        )
        main(["gate", "--run-id", meta.run_id, "--repo-path", str(repo)])
        main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "validator",
                "--runner",
                "echo",
                "--approve",
                "--repo-path",
                str(repo),
            ]
        )
        main(["report", "--run-id", meta.run_id, "--repo-path", str(repo)])
        report = (
            repo / ".governor" / "runs" / meta.run_id / "09_final_report.md"
        ).read_text()
        assert "## Repair history" in report
        assert repair_output_name(1) in report
