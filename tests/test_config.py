"""Tests for local runner profile config."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from governor.cli import main
from governor.config import (
    CONFIG_NOT_FOUND_MSG,
    check_secret_argv,
    config_path,
    init_config,
    load_profiles,
    parse_profile,
    validate_config_file,
    validate_profile_name,
)
from governor.utils import governor_root


def test_config_init_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        path = init_config(repo)
        assert path.is_file()
        assert path == config_path(repo)
        assert not (repo / ".governor" / "runs").exists()


def test_config_init_no_overwrite_without_force():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        init_config(repo)
        with pytest.raises(FileExistsError):
            init_config(repo, force=False)


def test_config_init_force_overwrites():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        path = init_config(repo)
        path.write_text("{}", encoding="utf-8")
        init_config(repo, force=True)
        data = json.loads(path.read_text())
        assert data["version"] == 1


def test_config_show_missing_returns_1():
    with tempfile.TemporaryDirectory() as tmp:
        rc = main(["config", "show", "--repo-path", str(Path(tmp))])
        assert rc == 1


def test_config_validate_valid_default_returns_0():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        init_config(repo)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "fake_agent.py").write_text("# fake\n", encoding="utf-8")
        rc = main(["config", "validate", "--repo-path", str(repo)])
        assert rc == 0


def test_invalid_json_returns_1():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        governor_root(repo).mkdir(parents=True)
        config_path(repo).write_text("{not json", encoding="utf-8")
        lines, has_fail = validate_config_file(config_path(repo), repo)
        assert has_fail
        assert any("JSON" in l.message for l in lines)


def test_bad_profile_name_rejected():
    with pytest.raises(ValueError):
        validate_profile_name("../evil")
    with pytest.raises(ValueError):
        validate_profile_name("Bad Name")


def test_enabled_command_empty_argv_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        governor_root(repo).mkdir(parents=True)
        data = {
            "version": 1,
            "profiles": {
                "bad-cmd": {
                    "runner": "command",
                    "argv": [],
                    "enabled": True,
                    "timeout": 300,
                }
            },
        }
        config_path(repo).write_text(json.dumps(data), encoding="utf-8")
        lines, has_fail = validate_config_file(config_path(repo), repo)
        assert has_fail
        assert any("empty argv" in l.message for l in lines)


def test_disabled_command_empty_argv_warn_only():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        governor_root(repo).mkdir(parents=True)
        data = {
            "version": 1,
            "profiles": {
                "off-cmd": {
                    "runner": "command",
                    "argv": [],
                    "enabled": False,
                    "timeout": 300,
                }
            },
        }
        config_path(repo).write_text(json.dumps(data), encoding="utf-8")
        lines, has_fail = validate_config_file(config_path(repo), repo)
        assert not has_fail
        assert any(l.level == "WARN" and "empty argv" in l.message for l in lines)


def test_invalid_timeout_rejected():
    with pytest.raises(ValueError, match="timeout"):
        parse_profile(
            "x",
            {"runner": "echo", "timeout": 99999, "enabled": True},
        )


def test_destructive_argv_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        governor_root(repo).mkdir(parents=True)
        data = {
            "version": 1,
            "profiles": {
                "nasty": {
                    "runner": "command",
                    "argv": ["git", "push", "origin", "main"],
                    "enabled": True,
                    "timeout": 60,
                }
            },
        }
        config_path(repo).write_text(json.dumps(data), encoding="utf-8")
        _, has_fail = validate_config_file(config_path(repo), repo)
        assert has_fail


def test_secret_argv_rejected():
    with pytest.raises(ValueError, match="secret"):
        check_secret_argv(["curl", "-H", "Bearer sk-abc123secret"])
    with pytest.raises(ValueError, match="secret"):
        check_secret_argv(["tool", "--password=supersecret"])


def test_config_path_does_not_create_governor():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        rc = main(["config", "path", "--repo-path", str(repo)])
        assert rc == 0
        assert not governor_root(repo).exists()


def test_config_show_redacts_secrets(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        governor_root(repo).mkdir(parents=True)
        data = {
            "version": 1,
            "profiles": {
                "leaky": {
                    "runner": "command",
                    "argv": ["echo", "token=abc123"],
                    "enabled": False,
                    "timeout": 60,
                }
            },
        }
        config_path(repo).write_text(json.dumps(data), encoding="utf-8")
        rc = main(["config", "show", "--repo-path", str(repo)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[REDACTED]" in out or "REDACTED" in out


def test_config_init_cli_message(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        rc = main(["config", "init", "--repo-path", str(Path(tmp))])
        assert rc == 0
        assert CONFIG_NOT_FOUND_MSG not in capsys.readouterr().out
