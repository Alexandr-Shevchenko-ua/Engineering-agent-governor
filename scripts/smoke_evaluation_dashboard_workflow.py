#!/usr/bin/env python3
"""Smoke: evaluation dashboard generation in a temp repo."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        ev_dir = repo / ".governor" / "evaluations"
        ev_dir.mkdir(parents=True)
        rows = [
            {
                "run_id": "20260101T100000Z_accepted-full",
                "task_category": "docs",
                "policy": "docs",
                "executor_profile": "cursor",
                "governor_provider": "cursor",
                "outcome": "PASS",
                "final_state": "FINAL_REPORT_READY",
                "final_report_exists": True,
                "evidence_bundle_exists": True,
                "review_package_exists": True,
                "evidence_completeness_score": 5,
                "governor_friction_score": 3.0,
                "run_success_score": 8.0,
                "reviewer_burden_reduction_signal": 7.0,
                "mr_outcome": "accepted",
                "manual_rework_minutes": 5,
                "gate_overall": "PASS",
                "annotations": [{"ts": "2026-01-01T00:00:00Z", "note": "ok"}],
                "evidence_quality_score": 5,
                "reviewer_burden_score": 2,
                "defect_types": [],
            },
            {
                "run_id": "20260101T110000Z_rejected-fail",
                "task_category": "bugfix",
                "policy": "bugfix",
                "executor_profile": "cursor",
                "governor_provider": "cursor",
                "outcome": "FAIL",
                "final_state": "FAILED",
                "final_report_exists": False,
                "evidence_bundle_exists": False,
                "review_package_exists": False,
                "evidence_completeness_score": 0,
                "governor_friction_score": 9.0,
                "run_success_score": 2.0,
                "reviewer_burden_reduction_signal": 2.0,
                "mr_outcome": "rejected",
                "manual_rework_minutes": 120,
                "gate_overall": "FAIL",
                "annotations": [{"ts": "2026-01-01T00:00:00Z", "note": "bad"}],
                "defect_types": ["logic"],
            },
            {
                "run_id": "20260101T120000Z_smoke-unknown",
                "task_category": "smoke",
                "policy": "default",
                "executor_profile": "cursor",
                "governor_provider": "cursor",
                "outcome": "PASS",
                "final_state": "INIT",
                "final_report_exists": False,
                "evidence_bundle_exists": False,
                "review_package_exists": False,
                "evidence_completeness_score": 1,
                "governor_friction_score": 1.0,
                "run_success_score": 5.0,
                "mr_outcome": "unknown",
                "gate_overall": "PASS",
                "validator_profile": "fake-validator",
            },
        ]
        index = ev_dir / "evaluations.jsonl"
        with index.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "governor",
                "evaluate",
                "dashboard",
                "--repo-path",
                str(repo),
                "--format",
                "both",
                "--include-smokes",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(proc.stderr or proc.stdout, file=sys.stderr)
            return proc.returncode

        md = ev_dir / "dashboard.md"
        html = ev_dir / "dashboard.html"
        if not md.is_file() or not html.is_file():
            print("dashboard files missing", file=sys.stderr)
            return 1
        md_text = md.read_text(encoding="utf-8")
        html_text = html.read_text(encoding="utf-8")
        for needle in (
            "Executive summary",
            "Cohort breakdown",
            "fake-validator",
            "Notes and caveats",
        ):
            if needle not in md_text:
                print(f"missing in md: {needle}", file=sys.stderr)
                return 1
        if "cdn" in html_text.lower() or "http://" in html_text:
            print("external assets in html", file=sys.stderr)
            return 1

    print("EVALUATION DASHBOARD SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
