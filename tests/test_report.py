"""Tests for report generation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governor.report import generate_reports
from governor.run_store import RunStore


def test_report_generation_minimal_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Report task")
        store.record_output(meta.run_id, "executor", text="## Plan\n- edit foo.py\n## Commands\n- pytest: pass")
        (run_dir / "08_gate_results.json").write_text(
            json.dumps({"overall": "PASS", "results": [], "changed_files_count": 1, "lines_added": 2, "lines_deleted": 0}),
            encoding="utf-8",
        )
        report_p, lead_p = generate_reports(store, meta.run_id)
        assert report_p.exists()
        assert lead_p.exists()
        body = report_p.read_text(encoding="utf-8")
        assert "Report task" in body
        assert "Executor output" in body or "executor" in body.lower()
        assert "08_gate_results" in body or "Gate" in body
        lead = lead_p.read_text(encoding="utf-8")
        assert "## Done" in lead
        assert "## Evidence" in lead
