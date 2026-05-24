"""Deterministic local gate checks (git, optional tooling, security heuristics)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from governor.redaction import redact

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

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "changed_files_count": self.changed_files_count,
            "lines_added": self.lines_added,
            "lines_deleted": self.lines_deleted,
            "suspicious_files": self.suspicious_files,
            "security_warnings": self.security_warnings,
            "results": [r.to_dict() for r in self.results],
        }


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
    rc, out, _ = _run_cmd(["git", "diff", "--numstat"], repo)
    if rc != 0:
        return 0, 0, 0, []
    files: list[str] = []
    added = deleted = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            try:
                added += int(parts[0]) if parts[0] != "-" else 0
                deleted += int(parts[1]) if parts[1] != "-" else 0
            except ValueError:
                pass
            files.append(parts[2])
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


def run_gates(target_repo: Path) -> GateReport:
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
        f"**Changed files:** {report.changed_files_count} (+{report.lines_added} / -{report.lines_deleted} lines)",
        "",
    ]
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
