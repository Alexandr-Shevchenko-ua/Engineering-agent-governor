"""Regression: report updates state/commands before rendering."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governor.models import RunState
from governor.report import REPORT_COMMAND_TEMPLATE, generate_reports
from governor.run_store import RunStore


def test_report_shows_final_state_and_report_command_once():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        store = RunStore(repo)
        run_dir, meta = store.create_run("Ordering test")
        store.record_output(meta.run_id, "executor", text="done")
        store.record_output(meta.run_id, "validator", text="Verdict: PASS\n")
        (run_dir / "08_gate_results.json").write_text(
            json.dumps({"overall": "PASS", "results": []}),
            encoding="utf-8",
        )

        generate_reports(store, meta.run_id)
        body = (run_dir / "09_final_report.md").read_text(encoding="utf-8")
        assert f"**State:** {RunState.FINAL_REPORT_READY.value}" in body
        def _report_cmd_lines(text: str) -> list[str]:
            return [
                line
                for line in text.splitlines()
                if line.strip().startswith("- `") and "governor report" in line
            ]

        assert len(_report_cmd_lines(body)) == 1

        generate_reports(store, meta.run_id)
        body2 = (run_dir / "09_final_report.md").read_text(encoding="utf-8")
        assert len(_report_cmd_lines(body2)) == 1

        state = json.loads((run_dir / "run_state.json").read_text())
        assert state["commands_executed"].count(
            REPORT_COMMAND_TEMPLATE.format(run_id=meta.run_id)
        ) == 1
