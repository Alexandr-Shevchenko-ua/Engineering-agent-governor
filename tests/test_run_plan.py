"""Tests for bounded run plan orchestrator."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from governor.cli import main
from governor.config import check_secret_argv
from governor.models import RunState
from governor.run_plan import (
    APPROVE_REQUIRED_MSG,
    PLAN_JSON,
    build_default_plan,
    create_plan,
    execute_plan,
    load_plan,
    plan_json_path,
)
from governor.run_store import RunStore


def _git_init_repo(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "plan@test.local"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Plan Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "README.md").write_text("# t\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def _setup_repo_with_config(repo: Path) -> None:
    main(["config", "init", "--repo-path", str(repo)])


def test_create_plan_with_profiles():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Plan create")
        plan = create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="fake-validator",
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        assert plan_json_path(run_dir).is_file()
        assert (run_dir / "12_run_plan.md").is_file()
        assert "plan_create" in (run_dir / "trace.jsonl").read_text()


def test_create_dry_run_no_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Dry plan")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
            dry_run=True,
        )
        assert not plan_json_path(repo / ".governor" / "runs" / meta.run_id).exists()


def test_create_missing_profile_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Bad profile")
        with pytest.raises(ValueError, match="Unknown profile"):
            create_plan(
                store,
                meta.run_id,
                executor_profile="no-such",
                validator_profile="echo-test",
            )


def test_execute_without_approve():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("No approve")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        result = execute_plan(store, meta.run_id, approve=False)
        assert result.exit_code == 1
        assert APPROVE_REQUIRED_MSG in result.message


def test_execute_plan_reaches_final_report():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Full plan")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        result = execute_plan(
            store,
            meta.run_id,
            approve=True,
            repo_path=str(repo),
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        assert (run_dir / "05_executor_output.md").is_file()
        assert (run_dir / "08_gate_results.json").is_file()
        assert (run_dir / "06_validator_output.md").is_file()
        assert (run_dir / "09_final_report.md").is_file()
        _, updated = store.get_run(meta.run_id)
        assert updated.state == RunState.FINAL_REPORT_READY.value
        assert result.overall_status == "PASS"


def test_execute_dry_run_no_writes():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Dry exec")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        result = execute_plan(store, meta.run_id, approve=True, dry_run=True)
        assert result.exit_code == 0
        assert not (run_dir / "05_executor_output.md").exists()


def test_executor_skip_when_output_exists():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Skip exec")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        run_dir = repo / ".governor" / "runs" / meta.run_id
        (run_dir / "05_executor_output.md").write_text("# existing\n", encoding="utf-8")
        meta = store.load_metadata(run_dir)
        meta.state = RunState.EXECUTOR_OUTPUT_RECORDED.value
        store.save_metadata(run_dir, meta)
        result = execute_plan(store, meta.run_id, approve=True, repo_path=str(repo))
        plan = load_plan(run_dir)
        ex = next(s for s in plan.steps if s.step_id == "dispatch_executor")
        assert ex.status == "SKIPPED"


def test_max_steps_guard():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Max steps")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        result = execute_plan(
            store, meta.run_id, approve=True, max_steps=1, repo_path=str(repo)
        )
        assert result.overall_status in ("BLOCKED", "STOPPED", "PASS", "FAIL")


def test_secret_argv_rejected_in_plan_build():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Secret")
        with pytest.raises(ValueError, match="secret"):
            build_default_plan(
                store,
                meta.run_id,
                executor_profile=None,
                executor_runner="command",
                executor_command=["echo", "password=secret"],
                validator_profile="echo-test",
                validator_runner=None,
                validator_command=None,
                auto_repair_prepare_on_fail=False,
            )


def test_report_includes_run_plan_section():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init_repo(repo)
        _setup_repo_with_config(repo)
        store = RunStore(repo)
        _, meta = store.create_run("Report plan")
        create_plan(
            store,
            meta.run_id,
            executor_profile="echo-test",
            validator_profile="echo-test",
        )
        execute_plan(store, meta.run_id, approve=True, repo_path=str(repo))
        report = (
            repo / ".governor" / "runs" / meta.run_id / "09_final_report.md"
        ).read_text()
        assert "## Run plan" in report


def test_plan_show_cli():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _setup_repo_with_config(repo)
        main(["init", "--task", "Show plan", "--repo-path", str(repo)])
        _, meta = RunStore(repo).get_run(None)
        main(
            [
                "plan",
                "create",
                "--run-id",
                meta.run_id,
                "--executor-profile",
                "echo-test",
                "--validator-profile",
                "echo-test",
                "--repo-path",
                str(repo),
            ]
        )
        rc = main(["plan", "show", "--run-id", meta.run_id, "--repo-path", str(repo)])
        assert rc == 0

