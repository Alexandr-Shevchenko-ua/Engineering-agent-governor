"""Read-only safety and local-config audit (no tests/smokes)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from governor.config import (
    CONFIG_FILENAME,
    check_secret_argv,
    config_path,
    load_profiles,
)
from governor.doctor import CheckResult
from governor.gates import is_git_worktree
from governor.governor_providers import (
    DEFAULT_CURSOR_GOVERNOR_PROFILE,
    argv_has_ask_mode,
    argv_looks_write_capable,
)
from governor.project_config import project_config_path, validate_project_data
from governor.repo_git import git_ls_files, git_tracked_under_governor
from governor.utils import governor_root, resolve_repo_path

GOVERNOR_PROVIDER_NAME_MARKERS = ("cursor-governor", "governor-auto")
EXECUTOR_WRITE_NAME_MARKERS = ("headless-local", "cursor-local")
EXECUTOR_ASK_NAME_MARKERS = ("ask", "read-only")
TRACKED_RUNTIME_PREFIXES = (".governor/", ".claude/")


@dataclass
class SafetyAuditSummary:
    results: list[CheckResult]
    overall: str  # PASS | FAIL

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "checks": [
                {"name": r.name, "status": r.status, "detail": r.detail}
                for r in self.results
            ],
        }


def _is_governor_provider_profile(name: str) -> bool:
    low = name.lower()
    return any(m in low for m in GOVERNOR_PROVIDER_NAME_MARKERS)


def _executor_profile_write_capable(name: str, description: str, argv: list[str]) -> bool:
    low = (name + " " + description).lower()
    if any(m in low for m in EXECUTOR_ASK_NAME_MARKERS):
        return False
    if argv_has_ask_mode(argv):
        return False
    if argv_looks_write_capable(argv):
        return True
    return any(m in low for m in EXECUTOR_WRITE_NAME_MARKERS)


def run_safety_audit(repo_path: str | Path) -> SafetyAuditSummary:
    repo = resolve_repo_path(str(repo_path))
    results: list[CheckResult] = []

    from governor.check import _check_governor_gitignored, _check_governor_not_tracked

    results.append(_check_governor_gitignored(repo))
    results.append(_check_governor_not_tracked(repo))

    cfg_p = config_path(repo)
    tracked_cfg = [p for p in git_ls_files(repo, ".governor") if p.endswith(CONFIG_FILENAME)]
    if tracked_cfg:
        results.append(
            CheckResult(
                "config_not_tracked",
                "FAIL",
                f".governor/{CONFIG_FILENAME} is tracked: {tracked_cfg[0]}",
            )
        )
    else:
        results.append(
            CheckResult(
                "config_not_tracked",
                "OK",
                f".governor/{CONFIG_FILENAME} not tracked",
            )
        )

    claude_tracked = git_ls_files(repo, ".claude")
    if claude_tracked:
        sample = ", ".join(claude_tracked[:3])
        results.append(
            CheckResult(
                "claude_not_tracked",
                "FAIL",
                f".claude/ tracked in git: {sample}",
            )
        )
    else:
        results.append(CheckResult("claude_not_tracked", "OK", ".claude/ not tracked"))

    proj = project_config_path(repo)
    if proj.is_file():
        try:
            data = json.loads(proj.read_text(encoding="utf-8"))
            lines = validate_project_data(data)
            fails = [ln.message for ln in lines if ln.level == "FAIL"]
            if fails:
                results.append(
                    CheckResult("project_config", "FAIL", "; ".join(fails[:3]))
                )
            else:
                results.append(CheckResult("project_config", "OK", "governor.project.json valid"))
        except (OSError, json.JSONDecodeError) as e:
            results.append(CheckResult("project_config", "FAIL", str(e)))
    else:
        results.append(
            CheckResult("project_config", "WARN", "no governor.project.json (optional)")
        )

    if not cfg_p.is_file():
        results.append(
            CheckResult(
                "local_config",
                "WARN",
                f"no {cfg_p} — run: python -m governor config init --repo-path .",
            )
        )
    else:
        results.append(CheckResult("local_config", "OK", f"found {cfg_p.name}"))
        try:
            profiles = load_profiles(cfg_p)
        except ValueError as e:
            results.append(CheckResult("profiles", "FAIL", str(e)))
            profiles = {}
        else:
            results.append(CheckResult("profiles", "OK", f"{len(profiles)} profile(s)"))

        for name, spec in profiles.items():
            if not spec.enabled:
                continue
            if spec.argv:
                try:
                    check_secret_argv(spec.argv)
                except ValueError as e:
                    results.append(
                        CheckResult(
                            f"profile_{name}_secrets",
                            "FAIL",
                            str(e),
                        )
                    )
            if _is_governor_provider_profile(name):
                if not spec.argv:
                    results.append(
                        CheckResult(
                            f"profile_{name}_governor",
                            "FAIL",
                            "enabled Governor provider profile has empty argv",
                        )
                    )
                elif not argv_has_ask_mode(spec.argv):
                    results.append(
                        CheckResult(
                            f"profile_{name}_governor",
                            "FAIL",
                            "enabled Governor provider must use --mode ask (read-only)",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            f"profile_{name}_governor",
                            "OK",
                            "Governor provider profile is ask/read-only",
                        )
                    )
            elif _executor_profile_write_capable(name, spec.description, spec.argv):
                hint = "write-capable executor — use only with dispatch --approve"
                if "write" not in spec.description.lower():
                    results.append(
                        CheckResult(
                            f"profile_{name}_executor",
                            "WARN",
                            f"{hint}; consider noting write-capable in description",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            f"profile_{name}_executor",
                            "OK",
                            f"enabled executor marked write-capable ({hint})",
                        )
                    )

        if DEFAULT_CURSOR_GOVERNOR_PROFILE in profiles:
            cg = profiles[DEFAULT_CURSOR_GOVERNOR_PROFILE]
            if cg.enabled and cg.argv and not argv_has_ask_mode(cg.argv):
                results.append(
                    CheckResult(
                        "cursor_governor_auto",
                        "FAIL",
                        "cursor-governor-auto enabled without --mode ask",
                    )
                )

    for prefix in TRACKED_RUNTIME_PREFIXES:
        tracked = git_ls_files(repo, prefix.rstrip("/"))
        if tracked:
            results.append(
                CheckResult(
                    f"runtime_{prefix.strip('/').replace('.', '_')}_tracked",
                    "FAIL",
                    f"{prefix} has tracked files ({len(tracked)})",
                )
            )

    gov_root = governor_root(repo)
    if gov_root.is_dir() and is_git_worktree(repo):
        if not git_tracked_under_governor(repo):
            results.append(
                CheckResult(
                    "runtime_artifacts",
                    "OK",
                    ".governor/ exists locally and is not tracked",
                )
            )

    overall = "FAIL" if any(r.status == "FAIL" for r in results) else "PASS"
    return SafetyAuditSummary(results=results, overall=overall)


def safety_audit_exit_code(summary: SafetyAuditSummary) -> int:
    return 0 if summary.overall == "PASS" else 1
