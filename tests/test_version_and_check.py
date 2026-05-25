"""Tests for version and check commands."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from governor import __version__
from governor.check import run_check
from governor.cli import main
from governor.project_config import default_project_config_dict


def test_version_string():
    assert __version__ == "1.2.0"


def test_version_command_text(capsys):
    assert main(["version"]) == 0
    out = capsys.readouterr().out
    assert "1.2.0" in out
    assert "Python" in out


def test_version_command_json(capsys):
    assert main(["version", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["version"] == "1.2.0"
    assert data["package"] == "engineering-agent-governor"
    assert "python_version" in data
    assert "platform" in data


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@test.local"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "README.md").write_text("# t\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".governor/\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def test_check_passes_in_temp_repo_with_valid_project():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        (repo / "governor.project.json").write_text(
            json.dumps(default_project_config_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        summary = run_check(str(repo), run_smoke=False)
        assert summary.overall == "PASS"
        names = {r.name for r in summary.results}
        assert "project_config" in names
        assert "governor_gitignored" in names


def test_check_fails_when_governor_tracked():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / ".governor").mkdir()
        (repo / ".governor" / "marker.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", ".governor"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "bad"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        summary = run_check(str(repo), run_smoke=False)
        assert summary.overall == "FAIL"
        tracked = [r for r in summary.results if r.name == "governor_not_tracked"]
        assert tracked and tracked[0].status == "FAIL"


def test_check_fails_invalid_project_config():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        bad = default_project_config_dict()
        bad["allowed_policies"] = ["not-real"]
        (repo / "governor.project.json").write_text(
            json.dumps(bad) + "\n",
            encoding="utf-8",
        )
        summary = run_check(str(repo), run_smoke=False)
        assert summary.overall == "FAIL"
        pc = [r for r in summary.results if r.name == "project_config"]
        assert pc and pc[0].status == "FAIL"


def test_check_cli_json():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        (repo / "governor.project.json").write_text(
            json.dumps(default_project_config_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        rc = main(["check", "--repo-path", str(repo), "--json"])
        assert rc == 0


def test_cli_help_smoke():
    for argv in [
        ["--help"],
        ["run", "start", "--help"],
        ["plan", "execute", "--help"],
        ["gate", "--help"],
        ["project", "validate", "--help"],
        ["check", "--help"],
    ]:
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 0
