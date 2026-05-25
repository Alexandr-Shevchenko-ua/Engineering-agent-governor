"""Tests for governor.project.json governance config."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from governor.cli import main
from governor.project_config import (
    default_project_config_dict,
    init_project_config,
    load_project_config,
    project_config_path,
    validate_project_data,
)


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
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def test_project_init_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        path = init_project_config(repo)
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == 1


def test_project_init_no_overwrite_without_force():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        init_project_config(repo)
        with pytest.raises(FileExistsError):
            init_project_config(repo)


def test_project_validate_valid_config():
    data = default_project_config_dict()
    lines = validate_project_data(data)
    assert not any(l.level == "FAIL" for l in lines)


def test_default_project_config_loads():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        from governor.project_config import init_project_config, load_project_config

        init_project_config(repo)
        cfg = load_project_config(repo)
        assert cfg.default_gate_profile == "fast"
        assert "agentic-tooling" in cfg.allowed_policies


def test_invalid_policy_fails_validation():
    data = default_project_config_dict()
    data["allowed_policies"] = ["not-a-real-policy"]
    lines = validate_project_data(data)
    assert any("unknown policy" in l.message for l in lines if l.level == "FAIL")


def test_invalid_gate_profile_name_fails():
    data = default_project_config_dict()
    data["gate_profiles"]["BAD NAME"] = data["gate_profiles"]["fast"]
    lines = validate_project_data(data)
    assert any(l.level == "FAIL" for l in lines)


def test_secret_in_config_fails():
    data = default_project_config_dict()
    data["project_name"] = "api_key=supersecretvalue123"
    lines = validate_project_data(data)
    assert any("secret" in l.message.lower() for l in lines if l.level == "FAIL")


def test_absolute_path_in_sensitive_paths_fails():
    data = default_project_config_dict()
    data["sensitive_paths"].append("/etc/passwd")
    lines = validate_project_data(data)
    assert any(l.level == "FAIL" for l in lines)


def test_cli_project_validate_ok():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        init_project_config(repo)
        rc = main(["project", "validate", "--repo-path", str(repo)])
        assert rc == 0


def test_resolve_policy_disallowed():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git_init(repo)
        init_project_config(repo)
        cfg_path = project_config_path(repo)
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["allowed_policies"] = ["default"]
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="not in allowed_policies"):
            from governor.project_config import resolve_policy_for_repo

            resolve_policy_for_repo(repo, "bugfix")
