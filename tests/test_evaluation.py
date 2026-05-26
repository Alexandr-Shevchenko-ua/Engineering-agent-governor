"""Tests for v1.4.0 run evaluation metrics."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from governor.cli import main
from governor.evaluation import (
    EVAL_JSON,
    EVAL_MD,
    annotate_run,
    evaluate_run,
    export_evaluations,
    extract_run_evaluation,
    load_all_evaluations,
)
from governor.trace import TraceLogger
from governor.utils import runs_dir

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "eval@test.local"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Eval Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "README.md").write_text("# t\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".governor/\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)


def _minimal_run(repo: Path) -> Path:
    rp = str(repo)
    assert main(["project", "init", "--repo-path", rp]) == 0
    assert main(["config", "init", "--repo-path", rp]) == 0
    assert (
        main(
            [
                "init",
                "--task",
                "Eval minimal run",
                "--policy",
                "docs",
                "--repo-path",
                rp,
            ]
        )
        == 0
    )
    run_dirs = sorted(runs_dir(repo).iterdir(), key=lambda p: p.name)
    run_dir = run_dirs[-1]
    run_id = run_dir.name

    (run_dir / "08_gate_results.json").write_text(
        json.dumps(
            {
                "overall": "WARN",
                "profile_compliance": "WARN",
                "changed_files_count": 2,
                "lines_added": 10,
                "lines_deleted": 1,
                "results": [
                    {"name": "pytest", "status": "PASS", "summary": "3 passed"},
                    {"name": "diff_budget", "status": "PASS"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "06_validator_output.md").write_text(
        "## Verdict\n\nPASS\n\nAll checks ok.\n",
        encoding="utf-8",
    )
    state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
    (run_dir / "12_run_plan.json").write_text(
        json.dumps(
            {
                "version": 1,
                "run_id": run_id,
                "repo_path": str(repo.resolve()),
                "created_at": state["created_at"],
                "updated_at": state["updated_at"],
                "executor_profile": "echo-test",
                "validator_profile": "fake-validator",
                "overall_status": "PASS",
                "steps": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "09_final_report.md").write_text("# Final\n", encoding="utf-8")
    (run_dir / "14_evidence_bundle.md").write_text("# Evidence\n", encoding="utf-8")
    (run_dir / "15_review_package.md").write_text("# Review\n", encoding="utf-8")

    trace = TraceLogger(run_dir, run_id)
    trace.append(
        phase="dispatch",
        actor="governor",
        action="dispatch_executor",
        status="ok",
        reason="profile=echo-test exit=0 duration=1.5s",
    )
    trace.append(phase="gate", actor="governor", action="gate", status="warn", reason="overall=WARN")
    trace.append(phase="repair", actor="governor", action="repair_prepare", status="ok")
    trace.append(phase="advisor", actor="advisor", action="advisor_ask", status="ok")

    state["outcome"] = "PASS"
    state["state"] = "FINAL_REPORT_READY"
    state["commands_executed"] = ["python -m governor gate --run-id x", "python -m governor plan execute --replace"]
    (run_dir / "run_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return run_dir


def test_evaluate_run_creates_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    run_dir = _minimal_run(repo)
    run_id = run_dir.name
    path, ev = evaluate_run(repo, run_id)
    assert path.name == EVAL_JSON
    assert (run_dir / EVAL_MD).is_file()
    assert ev["run_id"] == run_id
    assert ev["gate_overall"] == "WARN"
    assert ev["gate_warn_count"] >= 1
    assert ev["gate_overall_is_warn"] is True


def test_extract_validator_verdict(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    run_dir = _minimal_run(repo)
    ev = extract_run_evaluation(repo, run_dir.name)
    assert ev["validator_verdict"] == "PASS"


def test_counts_repair_advisor_checkpoint(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    run_dir = _minimal_run(repo)
    ev = extract_run_evaluation(repo, run_dir.name)
    assert ev["advisor_calls_count"] >= 1
    assert ev["repair_loops_count"] >= 0


def test_annotate_updates_scores(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    run_dir = _minimal_run(repo)
    run_id = run_dir.name
    evaluate_run(repo, run_id)
    ev = annotate_run(
        repo,
        run_id,
        manual_rework_minutes=5,
        mr_outcome="accepted",
        evidence_quality_score=4,
        reviewer_burden_score=2,
    )
    assert ev["mr_outcome"] == "accepted"
    assert ev["manual_rework_minutes"] == 5
    assert ev["governor_friction_score"] >= 10
    assert len(ev.get("annotations") or []) >= 1


def test_invalid_annotation_fails(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    run_dir = _minimal_run(repo)
    run_id = run_dir.name
    evaluate_run(repo, run_id)
    with pytest.raises(ValueError, match="mr_outcome"):
        annotate_run(repo, run_id, mr_outcome="invalid_outcome")
    with pytest.raises(ValueError, match="evidence_quality_score"):
        annotate_run(repo, run_id, evidence_quality_score=9)


def test_export_formats(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    run_dir = _minimal_run(repo)
    evaluate_run(repo, run_dir.name)
    csv_p = export_evaluations(repo, fmt="csv")
    assert csv_p.suffix == ".csv"
    assert csv_p.read_text(encoding="utf-8")
    md_p = export_evaluations(repo, fmt="markdown")
    assert "Governor run evaluations" in md_p.read_text(encoding="utf-8")
    jl_p = export_evaluations(repo, fmt="jsonl")
    assert jl_p.name == "evaluations.jsonl"


def test_summary_by_policy_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    run_dir = _minimal_run(repo)
    evaluate_run(repo, run_dir.name)
    assert main(["evaluate", "summary", "--repo-path", str(repo), "--by", "policy"]) == 0
    out = capsys.readouterr().out
    assert "docs" in out or "Runs evaluated" in out


def test_jsonl_idempotent_by_run_id(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    run_dir = _minimal_run(repo)
    run_id = run_dir.name
    evaluate_run(repo, run_id)
    evaluate_run(repo, run_id)
    rows = load_all_evaluations(repo)
    assert sum(1 for r in rows if r.get("run_id") == run_id) == 1


def test_cli_evaluate_run(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    run_dir = _minimal_run(repo)
    assert main(["evaluate", "run", "--run-id", run_dir.name, "--repo-path", str(repo)]) == 0


def test_docs_mention_rework_burden() -> None:
    text = (DOCS / "EVALUATION_METRICS.md").read_text(encoding="utf-8").lower()
    assert "rework" in text
    assert "reviewer" in text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "1.5" in readme or "evaluation" in readme.lower()
