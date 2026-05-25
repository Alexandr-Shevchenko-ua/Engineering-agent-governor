"""Run id validation and CLI rejection of path-like ids."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from governor.cli import main
from governor.run_store import RunStore
from governor.utils import validate_run_id


def test_valid_run_id_accepted():
    rid = "20260524T214854Z_add-indexjson-run-discovery"
    assert validate_run_id(rid) == rid


def test_none_allowed():
    assert validate_run_id(None) is None


def test_absolute_path_rejected():
    with pytest.raises(ValueError, match="not a path"):
        validate_run_id("/tmp/20260524T214854Z_foo")


def test_governor_runs_prefix_rejected():
    with pytest.raises(ValueError, match="not a path"):
        validate_run_id(".governor/runs/20260524T214854Z_foo")


def test_parent_traversal_rejected():
    with pytest.raises(ValueError, match="not a path"):
        validate_run_id("../some-run")


def test_backslash_path_rejected():
    with pytest.raises(ValueError, match="not a path"):
        validate_run_id("runs\\20260524T214854Z_foo")


def test_empty_rejected():
    with pytest.raises(ValueError):
        validate_run_id("")


def test_invalid_validator_record_no_artifact():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        _, meta = store.create_run("No artifact on bad id")
        with pytest.raises(ValueError, match="not a path"):
            store.record_output(
                "/home/x/.governor/runs/" + meta.run_id,
                "validator",
                text="Verdict: PASS\n",
            )
        assert not (repo / ".governor" / "runs" / meta.run_id / "06_validator_output.md").exists()


@pytest.mark.parametrize(
    "cmd",
    [
        ["status", "--run-id", "/tmp/bad-run-id"],
        ["record", "--run-id", "/tmp/bad", "--role", "executor", "--text", "x"],
        ["gate", "--run-id", "/tmp/bad"],
        ["report", "--run-id", "/tmp/bad"],
        [
            "dispatch",
            "--run-id",
            "/tmp/bad",
            "--role",
            "executor",
            "--runner",
            "echo",
        ],
    ],
)
def test_cli_rejects_path_like_run_id(cmd):
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        main(["init", "--task", "CLI validate", "--repo-path", str(repo)])
        full_cmd = cmd + ["--repo-path", str(repo)]
        assert main(full_cmd) == 1
