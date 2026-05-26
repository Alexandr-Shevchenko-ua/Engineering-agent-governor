"""Local meta-check for Governor development and release validation."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from governor import __version__
from governor.doctor import CheckResult
from governor.gates import is_git_worktree
from governor.repo_git import git_check_ignore, git_tracked_under_governor
from governor.project_config import (
    PROJECT_CONFIG_FILENAME,
    project_config_path,
    validate_project_data,
)
from governor.safety_audit import run_safety_audit
from governor.utils import resolve_repo_path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent

SMOKE_SCRIPTS = sorted(PACKAGE_ROOT.glob("scripts/smoke_*.py"))


@dataclass
class CheckSummary:
    results: list[CheckResult]
    overall: str  # PASS, FAIL

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "version": __version__,
            "checks": [
                {"name": r.name, "status": r.status, "detail": r.detail}
                for r in self.results
            ],
        }


def _check_version() -> CheckResult:
    return CheckResult("version", "OK", __version__)


def _check_project_config(repo: Path) -> CheckResult:
    path = project_config_path(repo)
    if not path.is_file():
        return CheckResult(
            "project_config",
            "WARN",
            f"no {PROJECT_CONFIG_FILENAME} (optional)",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return CheckResult("project_config", "FAIL", f"invalid JSON: {e}")
    lines = validate_project_data(data)
    fails = [ln.message for ln in lines if ln.level == "FAIL"]
    if fails:
        return CheckResult("project_config", "FAIL", "; ".join(fails[:3]))
    return CheckResult("project_config", "OK", f"valid {PROJECT_CONFIG_FILENAME}")


def _check_governor_gitignored(repo: Path) -> CheckResult:
    gitignore = repo / ".gitignore"
    if gitignore.is_file():
        text = gitignore.read_text(encoding="utf-8")
        if ".governor/" in text or "\n.governor\n" in text or text.strip() == ".governor":
            rule_ok = True
        else:
            rule_ok = any(line.strip().startswith(".governor") for line in text.splitlines())
        if rule_ok and not is_git_worktree(repo):
            return CheckResult(
                "governor_gitignored",
                "OK",
                ".governor/ present in .gitignore",
            )
    else:
        rule_ok = False

    if not is_git_worktree(repo):
        return CheckResult(
            "governor_gitignored",
            "WARN",
            "not a git repo — cannot verify ignore",
        )
    for candidate in (".governor/", ".governor", ".governor/config.json"):
        if git_check_ignore(repo, candidate):
            return CheckResult("governor_gitignored", "OK", f"{candidate} is gitignored")
    if rule_ok:
        return CheckResult(
            "governor_gitignored",
            "OK",
            ".governor/ listed in .gitignore",
        )
    return CheckResult(
        "governor_gitignored",
        "FAIL",
        ".governor is not ignored — add .governor/ to .gitignore",
    )


def _check_governor_not_tracked(repo: Path) -> CheckResult:
    tracked = git_tracked_under_governor(repo)
    if not tracked:
        return CheckResult("governor_not_tracked", "OK", "no tracked files under .governor/")
    sample = ", ".join(tracked[:5])
    more = f" (+{len(tracked) - 5} more)" if len(tracked) > 5 else ""
    return CheckResult(
        "governor_not_tracked",
        "FAIL",
        f"tracked .governor files: {sample}{more}",
    )


def _check_pytest(repo: Path) -> CheckResult:
    tests_dir = repo / "tests"
    if not tests_dir.is_dir():
        return CheckResult("pytest", "WARN", "no tests/ directory (skipped)")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode == 0:
        summary = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else "passed"
        return CheckResult("pytest", "OK", summary or "tests passed")
    tail = (proc.stdout or proc.stderr or "").strip()[-400:]
    return CheckResult("pytest", "FAIL", tail or f"exit {proc.returncode}")


def _check_smoke_scripts() -> list[CheckResult]:
    results: list[CheckResult] = []
    if not SMOKE_SCRIPTS:
        results.append(
            CheckResult("smoke_scripts", "WARN", f"no scripts under {PACKAGE_ROOT / 'scripts'}")
        )
        return results
    failed: list[str] = []
    for script in SMOKE_SCRIPTS:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=PACKAGE_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            failed.append(script.name)
    if failed:
        results.append(
            CheckResult(
                "smoke_scripts",
                "FAIL",
                f"failed: {', '.join(failed)}",
            )
        )
    else:
        results.append(
            CheckResult(
                "smoke_scripts",
                "OK",
                f"{len(SMOKE_SCRIPTS)} smoke script(s) passed",
            )
        )
    return results


def run_check(
    repo_path: str = ".",
    *,
    run_smoke: bool = False,
) -> CheckSummary:
    repo = resolve_repo_path(repo_path)
    results: list[CheckResult] = [
        _check_version(),
        _check_project_config(repo),
        _check_governor_gitignored(repo),
        _check_governor_not_tracked(repo),
    ]
    safety = run_safety_audit(repo)
    for r in safety.results:
        if r.name in ("governor_gitignored", "governor_not_tracked", "project_config"):
            continue
        results.append(r)
    results.append(_check_pytest(repo))
    if run_smoke:
        results.extend(_check_smoke_scripts())

    overall = "PASS"
    if any(r.status == "FAIL" for r in results):
        overall = "FAIL"
    return CheckSummary(results=results, overall=overall)


def check_exit_code(summary: CheckSummary) -> int:
    return 0 if summary.overall == "PASS" else 1
