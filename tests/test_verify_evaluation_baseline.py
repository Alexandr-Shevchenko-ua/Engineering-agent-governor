"""Tests for verify_evaluation_baseline.py script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_evaluation_baseline.py"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
    )


def test_baseline_skips_without_governor(tmp_path: Path) -> None:
    proc = _run("--repo-path", str(tmp_path))
    assert proc.returncode == 0
    assert "WARN" in proc.stdout


def test_baseline_ok_with_index(tmp_path: Path) -> None:
    ev = tmp_path / ".governor" / "evaluations"
    ev.mkdir(parents=True)
    row = {
        "run_id": "20260101T100000Z_test",
        "annotations": [{"ts": "t", "note": "n"}],
        "mr_outcome": "accepted",
        "manual_rework_minutes": 0,
        "evidence_quality_score": 3,
        "reviewer_burden_score": 3,
    }
    (ev / "evaluations.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    proc = _run("--repo-path", str(tmp_path), "--min-runs", "1")
    assert proc.returncode == 0
    assert "BASELINE OK" in proc.stdout


def test_baseline_fail_require(tmp_path: Path) -> None:
    proc = _run("--repo-path", str(tmp_path), "--require")
    assert proc.returncode == 1
    assert "FAIL" in proc.stderr
