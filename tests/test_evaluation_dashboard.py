"""Tests for evaluation dashboard lite (v1.5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from governor.evaluation_dashboard import (
    COHORT_FULL_EVIDENCE,
    COHORT_INCOMPLETE,
    COHORT_SMOKE,
    NO_EVALUATIONS_MSG,
    DashboardOptions,
    build_dashboard_summary,
    filter_rows,
    generate_dashboard,
    infer_cohort,
    render_dashboard_html,
    render_dashboard_markdown,
)


def _sample_row(
    run_id: str,
    *,
    friction: float = 5.0,
    success: float = 7.0,
    mr: str = "accepted",
    outcome: str = "PASS",
    final_state: str = "FINAL_REPORT_READY",
    report: bool = True,
    evidence: bool = True,
    review: bool = True,
    policy: str = "docs",
    executor: str = "cursor",
    provider: str = "cursor",
    rework: int = 0,
    annotated: bool = True,
) -> dict:
    row = {
        "run_id": run_id,
        "task_category": "docs",
        "policy": policy,
        "executor_profile": executor,
        "governor_provider": provider,
        "outcome": outcome,
        "final_state": final_state,
        "final_report_exists": report,
        "evidence_bundle_exists": evidence,
        "review_package_exists": review,
        "evidence_completeness_score": 4 if evidence else 1,
        "governor_friction_score": friction,
        "run_success_score": success,
        "reviewer_burden_reduction_signal": 6.0,
        "mr_outcome": mr,
        "manual_rework_minutes": rework,
        "gate_overall": "PASS",
        "validator_profile": "fake-validator",
        "defect_types": [],
        "pr_body_exists": True,
    }
    if annotated:
        row["annotations"] = [{"ts": "2026-01-01T00:00:00Z", "note": "test"}]
        row["evidence_quality_score"] = 4
        row["reviewer_burden_score"] = 2
    return row


def _write_index(repo: Path, rows: list[dict]) -> Path:
    ev_dir = repo / ".governor" / "evaluations"
    ev_dir.mkdir(parents=True, exist_ok=True)
    path = ev_dir / "evaluations.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return path


def test_dashboard_fails_when_evaluations_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="No evaluations found"):
        generate_dashboard(tmp_path, fmt="markdown")


def test_dashboard_fails_clear_message(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError) as exc:
        generate_dashboard(tmp_path)
    assert NO_EVALUATIONS_MSG in str(exc.value)
    assert "evaluate run" in str(exc.value)


def test_cohort_inference() -> None:
    full = _sample_row("a", evidence=True, review=True, report=True)
    assert infer_cohort(full) == COHORT_FULL_EVIDENCE

    no_exp = _sample_row("b", evidence=False, review=False, report=True, outcome="PASS")
    assert infer_cohort(no_exp) != COHORT_FULL_EVIDENCE

    smoke = _sample_row(
        "c",
        mr="unknown",
        evidence=False,
        review=False,
        report=False,
        outcome="FAIL",
        final_state="INIT",
    )
    assert infer_cohort(smoke) == COHORT_SMOKE

    fail = _sample_row("d", outcome="FAIL", final_state="FAILED")
    assert infer_cohort(fail) == COHORT_INCOMPLETE


def test_filter_excludes_smoke_by_default() -> None:
    rows = [
        _sample_row("good"),
        _sample_row("smoke", mr="unknown", evidence=False, review=False, report=False),
    ]
    opts = DashboardOptions(include_smokes=False)
    filtered = filter_rows(rows, opts)
    assert len(filtered) == 1


def test_summary_by_policy() -> None:
    rows = [
        _sample_row("r1", policy="docs", friction=8, success=3),
        _sample_row("r2", policy="bugfix", friction=2, success=9),
    ]
    filtered = filter_rows(rows, DashboardOptions(include_smokes=True))
    summary = build_dashboard_summary(rows, filtered, DashboardOptions(top_n=2))
    assert "docs" in summary["by_policy"]
    assert summary["by_policy"]["docs"]["count"] == 1


def test_worst_best_sorting() -> None:
    rows = [
        _sample_row("worst", friction=9, success=2),
        _sample_row("best", friction=1, success=9),
        _sample_row("mid", friction=5, success=5),
    ]
    filtered = filter_rows(rows, DashboardOptions(include_smokes=True))
    summary = build_dashboard_summary(rows, filtered, DashboardOptions(top_n=2))
    assert summary["worst_runs"][0]["run_id"] == "worst"
    assert summary["best_runs"][0]["run_id"] == "best"


def test_markdown_and_html_generated(tmp_path: Path) -> None:
    rows = [
        _sample_row("20260101T120000Z_accepted", mr="accepted"),
        _sample_row(
            "20260101T120001Z_rejected",
            mr="rejected",
            outcome="FAIL",
            friction=9,
            success=1,
        ),
        _sample_row(
            "20260101T120002Z_smoke",
            mr="unknown",
            evidence=False,
            review=False,
            report=False,
            annotated=False,
        ),
    ]
    _write_index(tmp_path, rows)
    result = generate_dashboard(tmp_path, fmt="both", include_smokes=True)
    assert result.markdown_path and result.markdown_path.is_file()
    assert result.html_path and result.html_path.is_file()
    md = result.markdown_path.read_text(encoding="utf-8")
    html_text = result.html_path.read_text(encoding="utf-8")
    assert "Executive summary" in md
    assert "Cohort breakdown" in md
    assert "fake-validator" in md
    assert "task_category" in md
    assert "http://" not in html_text and "https://" not in html_text
    assert "cdn" not in html_text.lower()
    assert "<script" not in html_text.lower()


def test_caveats_in_markdown() -> None:
    rows = [_sample_row("r1")]
    summary = build_dashboard_summary(
        rows, filter_rows(rows, DashboardOptions()), DashboardOptions()
    )
    summary["_filtered_rows"] = rows
    md = render_dashboard_markdown(summary)
    assert "fake-validator" in md
    assert "task_category" in md
    assert "heuristics" in md.lower()


def test_html_no_external_assets() -> None:
    rows = [_sample_row("r1")]
    summary = build_dashboard_summary(
        rows, filter_rows(rows, DashboardOptions()), DashboardOptions()
    )
    summary["_filtered_rows"] = rows
    html_text = render_dashboard_html(summary)
    assert "cdn.jsdelivr" not in html_text
    assert "<link" not in html_text
