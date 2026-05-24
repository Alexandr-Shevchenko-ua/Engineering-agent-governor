"""CLI parser and integration smoke tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from governor.cli import main
from governor import __version__
from governor.run_store import open_store


def test_version_exits_zero():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_version_string():
    assert __version__ == "0.2.1"


def test_status_repo_path_after_subcommand():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        assert main(["init", "--task", "CLI test", "--repo-path", str(repo)]) == 0
        assert main(["status", "--repo-path", str(repo)]) == 0


def test_status_repo_path_before_subcommand():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        main(["init", "--task", "Global repo path", "--repo-path", str(repo)])
        assert main(["--repo-path", str(repo), "status"]) == 0


def test_status_without_governor_fails_without_creating_dot_governor():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        assert not (repo / ".governor").exists()
        rc = main(["status", "--repo-path", str(repo)])
        assert rc == 1
        assert not (repo / ".governor").exists()


def test_record_overwrite_cli():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        main(["init", "--task", "CLI overwrite", "--repo-path", str(repo)])
        _, meta = open_store(str(repo)).get_run(None)
        run_id = meta.run_id
        assert main(["record", "--run-id", run_id, "--role", "executor", "--text", "v1", "--repo-path", str(repo)]) == 0
        assert main(["record", "--run-id", run_id, "--role", "executor", "--text", "v2", "--repo-path", str(repo)]) == 1
        assert main(["record", "--run-id", run_id, "--role", "executor", "--text", "v2", "--replace", "--repo-path", str(repo)]) == 0


def test_open_store_requires_runs():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        with pytest.raises(FileNotFoundError, match="Governor runs not found"):
            open_store(str(repo))
