"""Execution preflight checks before governed run plan dispatch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from governor.config import config_path, validate_config_file
from governor.doctor import CheckResult, _check_git, _check_repo_path
from governor.gates import is_git_worktree
from governor.project_config import (
    PROJECT_CONFIG_FILENAME,
    load_project_config,
    project_config_path,
    validate_project_data,
)
from governor.utils import resolve_repo_path


def _check_governor_gitignored(repo: Path) -> CheckResult:
    if not is_git_worktree(repo):
        return CheckResult(
            "governor_gitignored",
            "WARN",
            "not a git repo — cannot verify .governor is ignored",
        )
    proc = subprocess.run(
        ["git", "check-ignore", "-q", ".governor"],
        cwd=repo,
        capture_output=True,
    )
    if proc.returncode == 0:
        return CheckResult("governor_gitignored", "OK", ".governor is gitignored")
    return CheckResult(
        "governor_gitignored",
        "WARN",
        ".governor may be tracked — ensure .gitignore contains .governor/",
    )


def _check_project_config(repo: Path) -> CheckResult:
    path = project_config_path(repo)
    if not path.is_file():
        return CheckResult(
            "project_config",
            "WARN",
            f"no {PROJECT_CONFIG_FILENAME} (optional for legacy repos)",
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return CheckResult("project_config", "FAIL", f"invalid JSON: {e}")
    lines = validate_project_data(raw)
    fails = [ln.message for ln in lines if ln.level == "FAIL"]
    if fails:
        return CheckResult("project_config", "FAIL", "; ".join(fails[:3]))
    try:
        load_project_config(repo)
    except ValueError as e:
        return CheckResult("project_config", "FAIL", str(e))
    return CheckResult("project_config", "OK", f"valid {PROJECT_CONFIG_FILENAME}")


def _check_profiles_config(repo: Path, *, need_profiles: bool) -> CheckResult:
    if not need_profiles:
        return CheckResult("profiles_config", "OK", "runner mode — config optional")
    path = config_path(repo)
    if not path.is_file():
        return CheckResult(
            "profiles_config",
            "FAIL",
            f"config missing at {path}; run: python -m governor config init --repo-path .",
        )
    lines, has_fail = validate_config_file(path, repo)
    if has_fail:
        fails = [ln.message for ln in lines if ln.level == "FAIL"][:3]
        return CheckResult("profiles_config", "FAIL", "; ".join(fails) or "invalid config")
    return CheckResult("profiles_config", "OK", f"valid config at {path}")


def run_execution_preflight(
    repo_path: str,
    *,
    use_profiles: bool,
    strict: bool = False,
) -> tuple[list[CheckResult], bool]:
    """
    Preflight before governed run execution with --approve.
    Returns (results, ok_to_proceed).
    """
    repo = resolve_repo_path(repo_path)
    results: list[CheckResult] = [
        _check_repo_path(repo),
        _check_git(repo),
        _check_governor_gitignored(repo),
        _check_project_config(repo),
        _check_profiles_config(repo, need_profiles=use_profiles),
    ]

    has_fail = any(r.status == "FAIL" for r in results)
    has_warn = any(r.status == "WARN" for r in results)

    if has_fail:
        return results, False
    if strict and has_warn:
        return results, False
    return results, True
