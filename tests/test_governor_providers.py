"""Tests for Governor Mode providers (v1.3 cursor-auto)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from governor.cli import main
from governor.config import default_config_dict
from governor.governor_providers import (
    DEFAULT_CURSOR_GOVERNOR_PROFILE,
    PROVIDER_CURSOR_AUTO,
    SAFETY_FLAG_PROVIDER_FAILED,
    argv_has_ask_mode,
    resolve_cursor_governor_profile,
    validate_cursor_governor_profile,
)
from governor.governor_mode import (
    SAFETY_FLAG_UNSTRUCTURED,
    apply_proposal,
    propose_governor_mode,
    validate_proposal,
)
from governor.config import ProfileSpec

ROOT = Path(__file__).resolve().parents[1]
FAKE_CURSOR = ROOT / "scripts" / "fake_cursor_governor.py"
DOCS = ROOT / "docs"


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "gov@test.local"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Gov Test"],
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


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    rp = str(repo)
    assert main(["project", "init", "--repo-path", rp]) == 0
    assert main(["config", "init", "--repo-path", rp]) == 0
    return repo


def _enable_cursor_fake(repo: Path, *, enabled: bool = True, argv: list[str] | None = None) -> None:
    cfg_path = repo / ".governor" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if argv is None:
        argv = [
            sys.executable,
            str(FAKE_CURSOR),
            "--mode",
            "ask",
            "--model",
            "auto",
        ]
    cfg.setdefault("profiles", {})["cursor-governor-auto"] = {
        "runner": "command",
        "description": "test",
        "argv": argv,
        "timeout": 120,
        "enabled": enabled,
    }
    for name in ("echo-test", "fake-validator"):
        if name in cfg.get("profiles", {}):
            cfg["profiles"][name]["enabled"] = True
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def test_default_config_has_disabled_cursor_governor_auto(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    profiles = default_config_dict(repo)["profiles"]
    assert "cursor-governor-auto" in profiles
    assert profiles["cursor-governor-auto"]["enabled"] is False
    assert profiles["cursor-governor-auto"]["argv"] == []


def test_argv_has_ask_mode() -> None:
    assert argv_has_ask_mode(["agent", "-p", "--mode", "ask"])
    assert not argv_has_ask_mode(["agent", "-p", "--mode", "write"])


def test_write_capable_argv_rejected() -> None:
    spec = ProfileSpec(
        name="bad",
        runner="command",
        description="",
        argv=["agent", "--mode", "write"],
        timeout=60,
        enabled=True,
    )
    with pytest.raises(ValueError, match="ask"):
        validate_cursor_governor_profile(spec)


def test_empty_argv_rejected(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    cfg_path = repo / ".governor" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["profiles"]["cursor-governor-auto"] = {
        "runner": "command",
        "description": "x",
        "argv": [],
        "timeout": 60,
        "enabled": True,
    }
    cfg_path.write_text(json.dumps(cfg) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty argv"):
        resolve_cursor_governor_profile(repo, DEFAULT_CURSOR_GOVERNOR_PROFILE)


def test_disabled_profile_rejected(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _enable_cursor_fake(repo, enabled=False)
    with pytest.raises(ValueError, match="disabled"):
        resolve_cursor_governor_profile(repo, DEFAULT_CURSOR_GOVERNOR_PROFILE)


def test_disabled_allowed_with_flag(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _enable_cursor_fake(repo, enabled=False)
    spec = resolve_cursor_governor_profile(
        repo,
        DEFAULT_CURSOR_GOVERNOR_PROFILE,
        allow_disabled=True,
    )
    assert spec.name == DEFAULT_CURSOR_GOVERNOR_PROFILE


def test_cursor_auto_propose_fake(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _enable_cursor_fake(repo)
    result = propose_governor_mode(
        repo,
        "Docs link task",
        provider=PROVIDER_CURSOR_AUTO,
        policy_hint="default",
    )
    assert result.ok
    pj = result.proposal_dir / "proposal.json"
    data = json.loads(pj.read_text(encoding="utf-8"))
    assert data["provider"] == PROVIDER_CURSOR_AUTO
    assert data.get("provider_profile") == DEFAULT_CURSOR_GOVERNOR_PROFILE
    assert data.get("provider_mode") == "ask/read-only"
    assert SAFETY_FLAG_PROVIDER_FAILED not in data.get("safety_flags", [])


def test_cursor_nonzero_exit_provider_failed(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    fail_argv = [sys.executable, str(FAKE_CURSOR), "--fail", "--mode", "ask"]
    _enable_cursor_fake(repo, argv=fail_argv)
    result = propose_governor_mode(
        repo,
        "fail task",
        provider=PROVIDER_CURSOR_AUTO,
    )
    assert result.ok
    data = json.loads((result.proposal_dir / "proposal.json").read_text(encoding="utf-8"))
    assert SAFETY_FLAG_PROVIDER_FAILED in data["safety_flags"]
    assert data["confidence"] == "LOW"
    val = validate_proposal(repo, result.proposal_id)
    assert not val.ok
    apply = apply_proposal(repo, result.proposal_id, approve=True)
    assert not apply.ok


def test_validate_includes_cursor_metadata(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _enable_cursor_fake(repo)
    result = propose_governor_mode(repo, "meta task", provider=PROVIDER_CURSOR_AUTO)
    val = validate_proposal(repo, result.proposal_id)
    checks = {d.check for d in val.decisions}
    assert "cursor_provider_mode" in checks


def test_docs_mention_cursor_read_only() -> None:
    doc = (DOCS / "CURSOR_GOVERNOR_PROVIDER.md").read_text(encoding="utf-8")
    assert "read-only" in doc.lower() or "read only" in doc.lower()
    assert "cursor-auto" in doc
    assert "proposal-only" in doc.lower() or "proposal only" in doc.lower()
