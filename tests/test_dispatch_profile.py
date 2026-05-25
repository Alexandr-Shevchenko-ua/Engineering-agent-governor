"""Tests for dispatch --profile integration."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

from governor.cli import main
from governor.config import config_path, init_config
from governor.dispatch import DEFAULT_TIMEOUT, preview_dispatch
from governor.models import RunState
from governor.run_store import RunStore
from governor.utils import governor_root


def _write_config(repo: Path, profiles: dict) -> None:
    governor_root(repo).mkdir(parents=True, exist_ok=True)
    config_path(repo).write_text(
        json.dumps({"version": 1, "profiles": profiles}, indent=2),
        encoding="utf-8",
    )


def test_profile_and_runner_mutually_exclusive():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        init_config(repo)
        main(["init", "--task", "Mutual", "--repo-path", str(repo)])
        _, meta = RunStore(repo).get_run(None)
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "dispatch",
                    "--run-id",
                    meta.run_id,
                    "--role",
                    "executor",
                    "--runner",
                    "echo",
                    "--profile",
                    "echo-test",
                    "--repo-path",
                    str(repo),
                ]
            )
        assert exc.value.code != 0


def test_unknown_profile_clear_error():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        init_config(repo)
        main(["init", "--task", "Unknown prof", "--repo-path", str(repo)])
        _, meta = RunStore(repo).get_run(None)
        rc = main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "executor",
                "--profile",
                "no-such-profile",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 1


def test_disabled_profile_fails_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        init_config(repo)
        main(["init", "--task", "Disabled", "--repo-path", str(repo)])
        _, meta = RunStore(repo).get_run(None)
        rc = main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "executor",
                "--profile",
                "cursor-local",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 1


def test_profile_echo_preview_no_output():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        init_config(repo)
        main(["init", "--task", "Echo prev", "--repo-path", str(repo)])
        _, meta = RunStore(repo).get_run(None)
        rc = main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "executor",
                "--profile",
                "echo-test",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        assert not (
            repo / ".governor" / "runs" / meta.run_id / "05_executor_output.md"
        ).exists()


def test_profile_echo_execute_transitions():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        init_config(repo)
        main(["init", "--task", "Echo exec", "--repo-path", str(repo)])
        _, meta = RunStore(repo).get_run(None)
        rc = main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "executor",
                "--profile",
                "echo-test",
                "--approve",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        _, updated = RunStore(repo).get_run(meta.run_id)
        assert updated.state == RunState.EXECUTOR_OUTPUT_RECORDED.value


def test_profile_fake_validator_after_gate():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "scripts").mkdir()
        fake = repo / "scripts" / "fake_agent.py"
        fake.write_text(
            'import sys\nprint("Verdict: PASS\\n")\n',
            encoding="utf-8",
        )
        _write_config(
            repo,
            {
                "echo-test": {"runner": "echo", "timeout": 300, "enabled": True},
                "fake-validator": {
                    "runner": "command",
                    "argv": [sys.executable, "scripts/fake_agent.py"],
                    "timeout": 300,
                    "enabled": True,
                },
            },
        )
        main(["init", "--task", "Val prof", "--repo-path", str(repo)])
        _, meta = RunStore(repo).get_run(None)
        main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "executor",
                "--profile",
                "echo-test",
                "--approve",
                "--repo-path",
                str(repo),
            ]
        )
        main(["gate", "--run-id", meta.run_id, "--repo-path", str(repo)])
        rc = main(
            [
                "dispatch",
                "--run-id",
                meta.run_id,
                "--role",
                "validator",
                "--profile",
                "fake-validator",
                "--approve",
                "--repo-path",
                str(repo),
            ]
        )
        assert rc == 0
        _, updated = RunStore(repo).get_run(meta.run_id)
        assert updated.state == RunState.VALIDATOR_OUTPUT_RECORDED.value


def test_cli_timeout_override():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _write_config(
            repo,
            {
                "echo-test": {
                    "runner": "echo",
                    "timeout": 120,
                    "enabled": True,
                }
            },
        )
        store = RunStore(repo)
        _, meta = store.create_run("Timeout override")
        from governor.config import get_profile

        prof, spec = get_profile(repo, "echo-test")
        preview = preview_dispatch(
            store,
            meta.run_id,
            "executor",
            spec,
            999,
            replace=False,
            profile_name="echo-test",
        )
        assert preview.timeout == 999
        assert prof.timeout == 120


def test_profile_timeout_when_cli_omitted():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _write_config(
            repo,
            {
                "echo-test": {
                    "runner": "echo",
                    "timeout": 42,
                    "enabled": True,
                }
            },
        )
        store = RunStore(repo)
        _, meta = store.create_run("Prof timeout")
        from governor.config import get_profile

        prof, spec = get_profile(repo, "echo-test")
        preview = preview_dispatch(
            store,
            meta.run_id,
            "executor",
            spec,
            prof.timeout,
            replace=False,
            profile_name="echo-test",
        )
        assert preview.timeout == 42


def test_trace_includes_profile_no_prompt_body():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        init_config(repo)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Trace prof")
        from governor.config import get_profile

        prof, spec = get_profile(repo, "echo-test")
        preview_dispatch(
            store,
            meta.run_id,
            "executor",
            spec,
            prof.timeout,
            replace=False,
            profile_name="echo-test",
        )
        trace = (run_dir / "trace.jsonl").read_text()
        assert "profile=echo-test" in trace
        assert "03_executor_prompt" not in trace or "lorem" not in trace.lower()


def test_governor_config_json_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        init_config(repo)
        assert config_path(repo).is_file()
        import subprocess

        proc = subprocess.run(
            ["git", "check-ignore", "-v", str(config_path(repo))],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            assert ".governor" in proc.stdout
