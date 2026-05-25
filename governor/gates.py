"""Deterministic local gate checks (git, optional tooling, security heuristics)."""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from governor.redaction import redact

if TYPE_CHECKING:
    from governor.project_config import ProjectConfig

SUSPICIOUS_PATH_PATTERNS = [
    re.compile(r"(?i)\.env"),
    re.compile(r"(?i)credentials?\.(json|ya?ml)"),
    re.compile(r"(?i)secrets?\.(json|toml|ya?ml)"),
    re.compile(r"(?i)id_rsa"),
    re.compile(r"(?i)\.pem$"),
    re.compile(r"(?i)private[_-]?key"),
]

TOKEN_IN_DIFF = re.compile(
    r"(?i)(api[_-]?key|secret|password|token)\s*[=:]\s*['\"]?[a-zA-Z0-9\-._]{8,}"
)
BEARER_IN_DIFF = re.compile(r"(?i)authorization\s*:\s*bearer\s+\S+")


def is_git_worktree(repo: Path) -> bool:
    """True if path is inside a git work tree (supports worktrees)."""
    rc, out, _ = _run_cmd(["git", "rev-parse", "--is-inside-work-tree"], repo)
    return rc == 0 and out.strip().lower() == "true"


def detect_secrets_in_diff(raw_diff: str) -> bool:
    """Scan unredacted diff for token-like patterns (used before redaction)."""
    if not raw_diff:
        return False
    return bool(TOKEN_IN_DIFF.search(raw_diff) or BEARER_IN_DIFF.search(raw_diff))


@dataclass
class GateResult:
    name: str
    status: str  # PASS, FAIL, WARN, SKIPPED
    command: str | None = None
    summary: str = ""
    details: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateReport:
    overall: str = "PASS"
    results: list[GateResult] = field(default_factory=list)
    changed_files_count: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    suspicious_files: list[str] = field(default_factory=list)
    security_warnings: list[str] = field(default_factory=list)
    gate_profile: str | None = None
    required_checks: list[str] = field(default_factory=list)
    optional_checks: list[str] = field(default_factory=list)
    profile_compliance: str | None = None

    def to_dict(self) -> dict:
        d = {
            "overall": self.overall,
            "changed_files_count": self.changed_files_count,
            "lines_added": self.lines_added,
            "lines_deleted": self.lines_deleted,
            "suspicious_files": self.suspicious_files,
            "security_warnings": self.security_warnings,
            "results": [r.to_dict() for r in self.results],
        }
        if self.gate_profile:
            d["gate_profile"] = self.gate_profile
            d["required_checks"] = list(self.required_checks)
            d["optional_checks"] = list(self.optional_checks)
            d["profile_compliance"] = self.profile_compliance
        return d


def _run_cmd(cmd: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError as e:
        return -1, "", str(e)


def _gate_from_cmd(
    name: str,
    cmd: list[str],
    cwd: Path,
    *,
    pass_codes: set[int] | None = None,
    warn_on_fail: bool = False,
) -> GateResult:
    pass_codes = pass_codes or {0}
    rc, out, err = _run_cmd(cmd, cwd)
    combined = redact((out + "\n" + err).strip())
    if rc in pass_codes:
        status = "PASS"
    elif warn_on_fail:
        status = "WARN"
    else:
        status = "FAIL"
    summary = combined.splitlines()[0] if combined else f"exit {rc}"
    if len(combined) > 2000:
        combined = combined[:2000] + "\n... (truncated)"
    return GateResult(
        name=name,
        status=status,
        command=" ".join(cmd),
        summary=summary[:500],
        details=combined,
    )


def _optional_tool_gate(
    name: str,
    executable: str,
    cmd: list[str],
    cwd: Path,
    *,
    detect_paths: list[Path] | None = None,
    skip_reason: str | None = None,
) -> GateResult | None:
    if shutil.which(executable) is None:
        return GateResult(
            name=name,
            status="SKIPPED",
            command=" ".join(cmd),
            summary=f"{executable} not found",
            details=skip_reason or f"Install {executable} to enable this gate.",
        )
    if detect_paths:
        if not any(p.exists() for p in detect_paths):
            return GateResult(
                name=name,
                status="SKIPPED",
                command=" ".join(cmd),
                summary="project config not found",
                details=f"None of {[str(p) for p in detect_paths]} exist.",
            )
    return _gate_from_cmd(name, cmd, cwd, warn_on_fail=True)


def _parse_numstat(repo: Path) -> tuple[int, int, int, list[str]]:
    files: list[str] = []
    added = deleted = 0
    seen_paths: set[str] = set()
    for cmd in (["git", "diff", "--numstat"], ["git", "diff", "--cached", "--numstat"]):
        rc, out, _ = _run_cmd(cmd, repo)
        if rc != 0:
            continue
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                path = parts[2]
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                try:
                    added += int(parts[0]) if parts[0] != "-" else 0
                    deleted += int(parts[1]) if parts[1] != "-" else 0
                except ValueError:
                    pass
                files.append(path)
    return len(files), added, deleted, files


def _security_scan(repo: Path, diff_text: str, changed_files: list[str]) -> tuple[list[str], list[str]]:
    suspicious: list[str] = []
    warnings: list[str] = []

    status_rc, status_out, _ = _run_cmd(["git", "status", "--short"], repo)
    scan_paths = changed_files
    if status_rc == 0:
        for line in status_out.splitlines():
            path_part = line[3:].strip().split(" -> ")[-1]
            if path_part and path_part not in scan_paths:
                scan_paths.append(path_part)

    for path in scan_paths:
        for pat in SUSPICIOUS_PATH_PATTERNS:
            if pat.search(path):
                suspicious.append(path)
                break

    if detect_secrets_in_diff(diff_text):
        warnings.append("Possible secret/token pattern detected in git diff")

    if len(scan_paths) > 50:
        warnings.append(f"Large change set: {len(scan_paths)} files in diff/status")

    return suspicious, warnings


def _governor_repo_root(target_repo: Path) -> Path:
    if (target_repo / "scripts" / "smoke_governor_workflow.py").is_file():
        return target_repo
    return Path(__file__).resolve().parent.parent


def _paths_matching_patterns(paths: list[str], patterns: list[str]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        for pat in patterns:
            if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path.lower(), pat.lower()):
                hits.append(path)
                break
            if pat.endswith("/") and path.startswith(pat.rstrip("/")):
                hits.append(path)
                break
    return hits


def _populate_diff_stats(report: GateReport, target_repo: Path) -> list[str]:
    rc, diff_out, _ = _run_cmd(["git", "diff"], target_repo)
    file_count, added, deleted, files = _parse_numstat(target_repo)
    report.changed_files_count = file_count
    report.lines_added = added
    report.lines_deleted = deleted
    suspicious, warnings = _security_scan(target_repo, diff_out, files)
    report.suspicious_files = suspicious
    report.security_warnings = warnings
    return files


def _gate_diff_budget(target_repo: Path, cfg: ProjectConfig) -> GateResult:
    file_count, added, deleted, _ = _parse_numstat(target_repo)
    b = cfg.diff_budget
    issues: list[str] = []
    if file_count > b.max_changed_files:
        issues.append(f"files {file_count} > max {b.max_changed_files}")
    if added > b.max_lines_added:
        issues.append(f"added {added} > max {b.max_lines_added}")
    if deleted > b.max_lines_deleted:
        issues.append(f"deleted {deleted} > max {b.max_lines_deleted}")
    if issues:
        return GateResult(
            name="diff_budget",
            status="WARN",
            summary="Diff budget exceeded",
            details="; ".join(issues),
        )
    return GateResult(
        name="diff_budget",
        status="PASS",
        summary=f"{file_count} files, +{added}/-{deleted} within budget",
    )


def _gate_sensitive_paths_project(
    target_repo: Path,
    cfg: ProjectConfig,
    changed_files: list[str],
) -> GateResult:
    status_rc, status_out, _ = _run_cmd(["git", "status", "--short"], target_repo)
    scan_paths = list(changed_files)
    if status_rc == 0:
        for line in status_out.splitlines():
            path_part = line[3:].strip().split(" -> ")[-1]
            if path_part and path_part not in scan_paths:
                scan_paths.append(path_part)
    hits = _paths_matching_patterns(scan_paths, cfg.sensitive_paths)
    if hits:
        return GateResult(
            name="sensitive_paths",
            status="FAIL",
            summary=f"{len(hits)} sensitive path(s) in change set",
            details="\n".join(hits[:30]),
        )
    return GateResult(
        name="sensitive_paths",
        status="PASS",
        summary="No project sensitive_paths matched",
    )


def _run_smoke_script(target_repo: Path, gate_name: str, script_name: str) -> GateResult:
    root = _governor_repo_root(target_repo)
    script = root / "scripts" / script_name
    if not script.is_file():
        return GateResult(
            name=gate_name,
            status="SKIPPED",
            summary=f"{script_name} not found",
            details=str(script),
        )
    cmd = [sys.executable, str(script)]
    return _gate_from_cmd(gate_name, cmd, root, pass_codes={0})


def _run_builtin_gate(
    name: str,
    target_repo: Path,
    *,
    project_config: ProjectConfig | None = None,
    changed_files: list[str] | None = None,
) -> GateResult | None:
    if name == "git_status_short":
        return _gate_from_cmd(name, ["git", "status", "--short"], target_repo)
    if name == "git_diff_stat":
        return _gate_from_cmd(name, ["git", "diff", "--stat"], target_repo)
    if name == "git_diff_check":
        return _gate_from_cmd(name, ["git", "diff", "--check"], target_repo)
    if name == "security_suspicious_files":
        files = changed_files or []
        if project_config:
            hits = _paths_matching_patterns(files, project_config.sensitive_paths)
            if hits:
                return GateResult(
                    name=name,
                    status="WARN",
                    summary=f"{len(hits)} heuristic suspicious path(s)",
                    details="\n".join(hits[:20]),
                )
        return GateResult(name=name, status="PASS", summary="No extra heuristic hits")
    if name == "pytest":
        g = _optional_tool_gate(
            "pytest",
            "pytest",
            ["pytest", "-q"],
            target_repo,
            detect_paths=[
                target_repo / "pytest.ini",
                target_repo / "pyproject.toml",
                target_repo / "tests",
                target_repo / "test",
            ],
        )
        return g
    if name == "ruff":
        return _optional_tool_gate(
            "ruff",
            "ruff",
            ["ruff", "check", "."],
            target_repo,
            detect_paths=[target_repo / "pyproject.toml", target_repo / "ruff.toml"],
        )
    if name == "mypy":
        return _optional_tool_gate(
            "mypy",
            "mypy",
            ["mypy", "."],
            target_repo,
            detect_paths=[target_repo / "mypy.ini", target_repo / "pyproject.toml"],
        )
    if name == "npm_test":
        pkg = target_repo / "package.json"
        if not pkg.exists():
            return GateResult(name=name, status="SKIPPED", summary="no package.json")
        return _optional_tool_gate("npm_test", "npm", ["npm", "test"], target_repo)
    smoke_map = {
        "smoke_governor": "smoke_governor_workflow.py",
        "smoke_dispatch": "smoke_dispatch_workflow.py",
        "smoke_profile": "smoke_profile_workflow.py",
        "smoke_repair": "smoke_repair_workflow.py",
        "smoke_plan": "smoke_plan_workflow.py",
        "smoke_resume_checkpoint_evidence": "smoke_resume_checkpoint_evidence_workflow.py",
        "smoke_policy": "smoke_policy_workflow.py",
        "smoke_governed_run": "smoke_governed_run_workflow.py",
    }
    if name in smoke_map:
        return _run_smoke_script(target_repo, name, smoke_map[name])
    if name == "smoke_all":
        scripts = list(smoke_map.items())
        failed = []
        for gate_name, script_file in scripts:
            r = _run_smoke_script(target_repo, gate_name, script_file)
            if r and r.status not in ("PASS", "SKIPPED"):
                failed.append(script_file)
        if failed:
            return GateResult(
                name="smoke_all",
                status="FAIL",
                summary=f"smoke failures: {', '.join(failed)}",
            )
        return GateResult(name="smoke_all", status="PASS", summary="All smoke scripts passed")
    if name == "diff_budget" and project_config:
        return _gate_diff_budget(target_repo, project_config)
    if name == "sensitive_paths" and project_config:
        return _gate_sensitive_paths_project(
            target_repo, project_config, changed_files or []
        )
    return GateResult(name=name, status="SKIPPED", summary="unknown built-in gate")


def _finalize_overall(
    report: GateReport,
    *,
    required: set[str],
    optional: set[str],
) -> None:
    result_map = {r.name: r.status for r in report.results}
    req_fail = False
    req_warn = False
    opt_warn = False
    for name in required:
        st = result_map.get(name, "SKIPPED")
        if st in ("FAIL", "SKIPPED"):
            req_fail = True
        elif st == "WARN":
            req_warn = True
    for name in optional:
        st = result_map.get(name, "SKIPPED")
        if st in ("FAIL", "WARN", "SKIPPED"):
            opt_warn = True

    if req_fail:
        report.profile_compliance = "FAIL"
        report.overall = "FAIL"
    elif req_warn or opt_warn:
        report.profile_compliance = "WARN"
        report.overall = "WARN"
    elif any(r.status == "FAIL" for r in report.results):
        report.overall = "FAIL"
        report.profile_compliance = "FAIL"
    elif any(r.status == "WARN" for r in report.results) or report.security_warnings:
        report.overall = "WARN"
        report.profile_compliance = report.profile_compliance or "WARN"
    else:
        report.overall = "PASS"
        report.profile_compliance = "PASS"


def _run_gates_legacy(target_repo: Path) -> GateReport:
    report = GateReport()
    is_git = is_git_worktree(target_repo)

    if not is_git:
        report.results.append(
            GateResult(
                name="git_available",
                status="SKIPPED",
                summary="Not a git repository",
                details=str(target_repo),
            )
        )
        report.overall = "WARN"
        return report

    report.results.append(
        _gate_from_cmd("git_status_short", ["git", "status", "--short"], target_repo)
    )
    report.results.append(
        _gate_from_cmd("git_diff_stat", ["git", "diff", "--stat"], target_repo)
    )
    report.results.append(
        _gate_from_cmd("git_diff_check", ["git", "diff", "--check"], target_repo)
    )

    rc, diff_out, _ = _run_cmd(["git", "diff"], target_repo)
    file_count, added, deleted, files = _parse_numstat(target_repo)
    report.changed_files_count = file_count
    report.lines_added = added
    report.lines_deleted = deleted

    # Security scan uses raw diff; stored gate details remain redacted.
    suspicious, warnings = _security_scan(target_repo, diff_out, files)
    report.suspicious_files = suspicious
    report.security_warnings = warnings

    if suspicious:
        report.results.append(
            GateResult(
                name="security_suspicious_files",
                status="WARN",
                summary=f"{len(suspicious)} suspicious path(s)",
                details="\n".join(suspicious),
            )
        )
    else:
        report.results.append(
            GateResult(
                name="security_suspicious_files",
                status="PASS",
                summary="No suspicious credential paths in change set",
            )
        )

    if warnings:
        for i, w in enumerate(warnings):
            report.results.append(
                GateResult(
                    name=f"security_heuristic_{i + 1}",
                    status="WARN",
                    summary=w,
                )
            )

    if file_count > 30 or (added + deleted) > 2000:
        report.results.append(
            GateResult(
                name="diff_size",
                status="WARN",
                summary=f"{file_count} files, +{added}/-{deleted} lines",
                details="Large diff — review scope creep.",
            )
        )

    # Optional gates
    optional = [
        _optional_tool_gate(
            "pytest",
            "pytest",
            ["pytest", "-q"],
            target_repo,
            detect_paths=[
                target_repo / "pytest.ini",
                target_repo / "pyproject.toml",
                target_repo / "tests",
                target_repo / "test",
            ],
        ),
        _optional_tool_gate(
            "ruff",
            "ruff",
            ["ruff", "check", "."],
            target_repo,
            detect_paths=[target_repo / "pyproject.toml", target_repo / "ruff.toml"],
        ),
        _optional_tool_gate(
            "mypy",
            "mypy",
            ["mypy", "."],
            target_repo,
            detect_paths=[target_repo / "mypy.ini", target_repo / "pyproject.toml"],
        ),
    ]

    pkg = target_repo / "package.json"
    if pkg.exists():
        pkg_text = pkg.read_text(encoding="utf-8")
        if '"test"' in pkg_text:
            if (target_repo / "pnpm-lock.yaml").exists() and shutil.which("pnpm"):
                optional.append(
                    _optional_tool_gate("npm_test", "pnpm", ["pnpm", "test"], target_repo)
                )
            elif (target_repo / "yarn.lock").exists() and shutil.which("yarn"):
                optional.append(
                    _optional_tool_gate("npm_test", "yarn", ["yarn", "test"], target_repo)
                )
            elif shutil.which("npm"):
                optional.append(
                    _optional_tool_gate("npm_test", "npm", ["npm", "test"], target_repo)
                )
        else:
            optional.append(
                GateResult(
                    name="npm_test",
                    status="SKIPPED",
                    summary="no test script in package.json",
                )
            )

    for g in optional:
        if g is not None:
            report.results.append(g)

    statuses = [r.status for r in report.results]
    if any(s == "FAIL" for s in statuses):
        report.overall = "FAIL"
    elif any(s == "WARN" for s in statuses) or report.security_warnings or report.suspicious_files:
        report.overall = "WARN"
    else:
        report.overall = "PASS"

    return report


def _run_gates_with_profile(
    target_repo: Path,
    profile_name: str,
    cfg: ProjectConfig,
) -> GateReport:
    spec = cfg.gate_profiles[profile_name]
    report = GateReport(
        gate_profile=profile_name,
        required_checks=list(spec.required),
        optional_checks=list(spec.optional),
    )
    report.results.append(
        GateResult(
            name="gate_profile",
            status="PASS",
            summary=f"Profile {profile_name}: {spec.description}",
        )
    )

    if not is_git_worktree(target_repo):
        report.results.append(
            GateResult(
                name="git_available",
                status="SKIPPED",
                summary="Not a git repository",
            )
        )
        report.overall = "WARN"
        report.profile_compliance = "WARN"
        return report

    changed_files = _populate_diff_stats(report, target_repo)

    required_set = set(spec.required)
    optional_set = set(spec.optional)
    seen: set[str] = set()

    for cmd_name in spec.commands:
        seen.add(cmd_name)
        is_required = cmd_name in required_set
        is_optional = cmd_name in optional_set
        g = _run_builtin_gate(
            cmd_name,
            target_repo,
            project_config=cfg,
            changed_files=changed_files,
        )
        if g is None:
            continue
        if is_required and g.status == "SKIPPED":
            g.status = "FAIL"
            g.summary = f"Required check skipped: {g.summary}"
        elif is_optional:
            if g.status == "FAIL":
                g.status = "WARN"
            elif g.status == "SKIPPED":
                g.status = "WARN"
        report.results.append(g)

    for name in required_set - seen:
        report.results.append(
            GateResult(
                name=name,
                status="FAIL",
                summary="Required check not in profile commands list",
            )
        )

    _finalize_overall(report, required=required_set, optional=optional_set)
    return report


def run_gates(
    target_repo: Path,
    *,
    gate_profile: str | None = None,
    project_config: ProjectConfig | None = None,
) -> GateReport:
    from governor.project_config import (
        load_project_config_optional,
        resolve_gate_profile_for_repo,
    )

    cfg = project_config or load_project_config_optional(target_repo)
    profile_name = gate_profile or (
        resolve_gate_profile_for_repo(target_repo, None) if cfg else None
    )

    if cfg and profile_name and profile_name in cfg.gate_profiles:
        return _run_gates_with_profile(target_repo, profile_name, cfg)
    return _run_gates_legacy(target_repo)


def write_gate_artifacts(run_dir: Path, report: GateReport) -> tuple[Path, Path]:
    json_path = run_dir / "08_gate_results.json"
    md_path = run_dir / "08_gate_results.md"

    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Gate results",
        "",
        f"**Overall:** {report.overall}",
        "",
    ]
    if report.gate_profile:
        lines.append(f"**Gate profile:** `{report.gate_profile}`")
        lines.append(f"**Profile compliance:** {report.profile_compliance or 'n/a'}")
        if report.required_checks:
            lines.append(f"**Required checks:** {', '.join(report.required_checks)}")
        if report.optional_checks:
            lines.append(f"**Optional checks:** {', '.join(report.optional_checks)}")
        lines.append("")
    lines.extend(
        [
            f"**Changed files:** {report.changed_files_count} "
            f"(+{report.lines_added} / -{report.lines_deleted} lines)",
            "",
        ]
    )
    if report.suspicious_files:
        lines.append("## Suspicious files")
        for f in report.suspicious_files:
            lines.append(f"- `{f}`")
        lines.append("")
    if report.security_warnings:
        lines.append("## Security warnings")
        for w in report.security_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## Checks")
    lines.append("")
    lines.append("| Gate | Status | Summary |")
    lines.append("|------|--------|---------|")
    for r in report.results:
        lines.append(f"| {r.name} | {r.status} | {r.summary[:80]} |")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
