"""Local readiness checks for Governor and a target repo."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from governor.config import config_path, validate_config_file
from governor.gates import is_git_worktree
from governor.index import index_path, load_index
from governor.utils import resolve_repo_path, runs_dir

CONFIG_INIT_HINT = "python -m governor config init --repo-path ."


@dataclass
class CheckResult:
    name: str
    status: str  # OK, WARN, FAIL
    detail: str


def _check_python() -> CheckResult:
    v = sys.version_info
    ok = v >= (3, 11)
    detail = f"{v.major}.{v.minor}.{v.micro}"
    return CheckResult(
        "python_version",
        "OK" if ok else "FAIL",
        detail + (" (requires >= 3.11)" if not ok else ""),
    )


def _check_repo_path(repo: Path) -> CheckResult:
    if not repo.exists():
        return CheckResult("repo_path", "FAIL", f"Path does not exist: {repo}")
    if not repo.is_dir():
        return CheckResult("repo_path", "FAIL", f"Not a directory: {repo}")
    return CheckResult("repo_path", "OK", str(repo))


def _check_git(repo: Path) -> CheckResult:
    if not shutil.which("git"):
        return CheckResult("git", "WARN", "git executable not found")
    if is_git_worktree(repo):
        return CheckResult("git_worktree", "OK", "inside git work tree")
    return CheckResult("git_worktree", "WARN", "not a git work tree")


def _check_runs(repo: Path) -> CheckResult:
    base = runs_dir(repo)
    if not base.is_dir():
        return CheckResult("governor_runs", "WARN", f"no runs at {base}")
    count = sum(1 for p in base.iterdir() if p.is_dir())
    return CheckResult("governor_runs", "OK", f"{count} run(s) under {base}")


def _check_index(repo: Path) -> CheckResult:
    path = index_path(repo)
    if not path.exists():
        base = runs_dir(repo)
        if base.is_dir() and any(base.iterdir()):
            return CheckResult("governor_index", "WARN", "index missing (can rebuild from run_state.json)")
        return CheckResult("governor_index", "WARN", "index not present yet")
    try:
        data = load_index(repo)
        n = len(data.get("runs", []))
        return CheckResult("governor_index", "OK", f"readable, {n} entries")
    except ValueError as e:
        return CheckResult("governor_index", "FAIL", str(e))


def _check_latest_run_state(repo: Path) -> CheckResult:
    base = runs_dir(repo)
    if not base.is_dir():
        return CheckResult("latest_run_state", "WARN", "no runs directory")
    dirs = sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    if not dirs:
        return CheckResult("latest_run_state", "WARN", "no runs")
    latest = dirs[0]
    state_file = latest / "run_state.json"
    if not state_file.exists():
        return CheckResult("latest_run_state", "FAIL", f"missing run_state.json in {latest.name}")
    try:
        import json

        json.loads(state_file.read_text(encoding="utf-8"))
        return CheckResult("latest_run_state", "OK", f"{latest.name}/run_state.json readable")
    except (OSError, json.JSONDecodeError) as e:
        return CheckResult("latest_run_state", "FAIL", str(e))


def _check_config(repo: Path) -> CheckResult:
    path = config_path(repo)
    if not path.is_file():
        return CheckResult(
            "governor_config",
            "WARN",
            f"config missing at {path}; run: {CONFIG_INIT_HINT}",
        )
    lines, has_fail = validate_config_file(path, repo)
    if has_fail:
        fails = [ln.message for ln in lines if ln.level == "FAIL"][:3]
        return CheckResult(
            "governor_config",
            "FAIL",
            "; ".join(fails) or "invalid config",
        )
    try:
        from governor.config import load_profiles

        profiles = len(load_profiles(path))
    except ValueError:
        profiles = 0
    return CheckResult(
        "governor_config",
        "OK",
        f"valid config, {profiles} profile(s)",
    )


def _check_optional_tool(name: str) -> CheckResult:
    if shutil.which(name):
        return CheckResult(f"tool_{name}", "OK", f"{name} available")
    return CheckResult(f"tool_{name}", "WARN", f"{name} not on PATH (optional)")


def run_doctor(repo_path: str | None = None) -> tuple[list[CheckResult], int]:
    """
    Run checks. Returns (results, exit_code).
    Exit 1 only for FAIL on required checks (repo, corrupted state/index).
    """
    repo = resolve_repo_path(repo_path)
    results: list[CheckResult] = [
        _check_python(),
        _check_repo_path(repo),
        _check_git(repo),
        _check_runs(repo),
        _check_config(repo),
        _check_index(repo),
        _check_latest_run_state(repo),
        _check_optional_tool("git"),
        _check_optional_tool("pytest"),
        _check_optional_tool("ruff"),
        _check_optional_tool("mypy"),
    ]

    exit_code = 0
    for r in results:
        if r.status == "FAIL":
            exit_code = 1
    return results, exit_code
