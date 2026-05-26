"""Tests for v1.3.1 stabilization (safety audit, cleanup, diagnose)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from governor.cli import main
from governor.cleanup import cleanup_proposals, cleanup_runs, cleanup_status
from governor.diagnose import diagnose_run
from governor.safety_audit import run_safety_audit
from governor.utils import proposals_dir, runs_dir

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "stab@test.local"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Stab Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "README.md").write_text("# t\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".governor/\n.claude/\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def _init_governor(repo: Path) -> None:
    rp = str(repo)
    assert main(["project", "init", "--repo-path", rp]) == 0
    assert main(["config", "init", "--repo-path", rp]) == 0


def test_safety_audit_pass_temp_repo(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    _init_governor(repo)
    summary = run_safety_audit(repo)
    assert summary.overall == "PASS"
    assert not any(r.status == "FAIL" for r in summary.results)


def test_safety_audit_fail_tracked_config(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    _init_governor(repo)
    cfg = repo / ".governor" / "config.json"
    subprocess.run(["git", "add", "-f", str(cfg)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "track config"], cwd=repo, check=True)
    summary = run_safety_audit(repo)
    assert summary.overall == "FAIL"
    assert any(r.name == "config_not_tracked" and r.status == "FAIL" for r in summary.results)


def test_safety_audit_fail_unsafe_governor_argv(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    _init_governor(repo)
    cfg = json.loads((repo / ".governor" / "config.json").read_text(encoding="utf-8"))
    cfg["profiles"]["cursor-governor-bad"] = {
        "runner": "command",
        "description": "bad",
        "argv": ["agent", "-p", "--mode", "write"],
        "timeout": 60,
        "enabled": True,
    }
    (repo / ".governor" / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")
    summary = run_safety_audit(repo)
    assert summary.overall == "FAIL"


def test_cleanup_dry_run_deletes_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    rbase = runs_dir(repo)
    rbase.mkdir(parents=True)
    for i in range(5):
        (rbase / f"2026010{i}T120000Z_run-{i}").mkdir()
    result = cleanup_runs(repo, keep_last=2, approve=False)
    assert result.dry_run is True
    assert len(result.removed) == 3
    assert len(list(rbase.iterdir())) == 5


def test_cleanup_approve_removes_old_runs(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    rbase = runs_dir(repo)
    rbase.mkdir(parents=True)
    names = [f"2026010{i}T120000Z_run-{i}" for i in range(5)]
    for n in names:
        (rbase / n).mkdir()
    result = cleanup_runs(repo, keep_last=2, approve=True)
    assert result.dry_run is False
    assert len(result.removed) == 3
    remaining = {p.name for p in rbase.iterdir() if p.is_dir()}
    assert remaining == {names[4], names[3]}


def test_cleanup_proposals_approve(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    pbase = proposals_dir(repo)
    pbase.mkdir(parents=True)
    for i in range(4):
        (pbase / f"2026010{i}T120000Z_prop-{i}").mkdir()
    result = cleanup_proposals(repo, keep_last=1, approve=True)
    assert len(result.removed) == 3
    assert len(list(pbase.iterdir())) == 1


def _write_run(repo: Path, run_id: str, state: str, *, gate_overall: str | None = None) -> Path:
    run_dir = runs_dir(repo) / run_id
    run_dir.mkdir(parents=True)
    meta = {
        "run_id": run_id,
        "task": "test",
        "repo_path": str(repo),
        "state": state,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "repair_count": 0,
        "repair_prompt_count": 0,
        "commands_executed": [],
        "outcome": None,
        "policy": "default",
    }
    (run_dir / "run_state.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    if gate_overall:
        (run_dir / "08_gate_results.json").write_text(
            json.dumps({"overall": gate_overall}, indent=2) + "\n",
            encoding="utf-8",
        )
    return run_dir


def test_diagnose_executor_prompt_ready(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    rid = "20260101T120000Z_diagnose-ready"
    _write_run(repo, rid, "EXECUTOR_PROMPT_READY")
    d = diagnose_run(repo, rid)
    assert d.state == "EXECUTOR_PROMPT_READY"
    assert "resume" in d.next_command or "dispatch" in d.next_command


def test_diagnose_gates_warn(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    rid = "20260101T120000Z_diagnose-gates"
    _write_run(repo, rid, "GATES_RUN", gate_overall="WARN")
    d = diagnose_run(repo, rid)
    assert d.gate_overall == "WARN"
    assert "continue-on-gate-warn" in d.next_command


def test_diagnose_final_report_ready(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    rid = "20260101T120000Z_diagnose-done"
    run_dir = _write_run(repo, rid, "FINAL_REPORT_READY")
    (run_dir / "09_final_report.md").write_text("# done\n", encoding="utf-8")
    d = diagnose_run(repo, rid)
    assert d.state == "FINAL_REPORT_READY"
    assert d.has_final_report
    assert "status" in d.next_command


def test_docs_architecture_role_boundaries() -> None:
    text = (DOCS / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "Cursor Governor Provider" in text
    assert "read-only" in text.lower() or "read only" in text.lower()
    assert "Chatbang Advisor" in text
    assert "Can modify repo?" in text


def test_docs_troubleshooting_common_failures() -> None:
    text = (DOCS / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
    for frag in (
        "git push",
        "ask mode",
        "run-id",
        "--replace",
        ".governor",
        "pytest",
    ):
        assert frag in text.lower() or frag in text


def test_cli_safety_audit_json(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    _init_governor(repo)
    proc = subprocess.run(
        [sys.executable, "-m", "governor", "safety", "audit", "--repo-path", str(repo), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["overall"] == "PASS"
