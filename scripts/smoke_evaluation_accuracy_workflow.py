#!/usr/bin/env python3
"""CI-safe smoke: v1.4.1 evaluation metric accuracy."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_gov(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "governor", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "acc@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Acc Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# acc\n", encoding="utf-8")
        (repo / ".gitignore").write_text(".governor/\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)

        rp = str(repo)
        for cmd in [
            ["project", "init", "--repo-path", rp],
            ["config", "init", "--repo-path", rp],
        ]:
            p = run_gov(cmd, cwd=repo)
            if p.returncode != 0:
                errors.append(f"{' '.join(cmd)}: {p.stderr or p.stdout}")

        init_p = run_gov(
            ["init", "--task", "Accuracy smoke", "--policy", "docs", "--repo-path", rp],
            cwd=repo,
        )
        if init_p.returncode != 0:
            errors.append(f"init: {init_p.stderr or init_p.stdout}")
            print("\n".join(errors), file=sys.stderr)
            return 1

        run_id = None
        for line in (init_p.stdout or "").splitlines():
            if line.startswith("Created run:"):
                run_id = line.split(":", 1)[1].strip()
        if not run_id:
            errors.append("no run_id")
            print("\n".join(errors), file=sys.stderr)
            return 1

        run_dir = repo / ".governor" / "runs" / run_id
        (run_dir / "08_gate_results.json").write_text(
            json.dumps(
                {
                    "overall": "WARN",
                    "profile_compliance": "WARN",
                    "profile_compliance_reason": "smoke optional profile gap",
                    "results": [{"name": "pytest", "status": "PASS"}],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "06_validator_output.md").write_text("## Verdict\n\nPASS\n", encoding="utf-8")
        (run_dir / "12_run_plan.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "run_id": run_id,
                    "repo_path": rp,
                    "created_at": "2026-05-25T12:00:00Z",
                    "updated_at": "2026-05-25T12:02:00Z",
                    "validator_profile": "fake-validator",
                    "executor_profile": "echo-test",
                    "overall_status": "PASS",
                    "steps": [],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        state_path = run_dir / "run_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["commands_executed"] = [
            "python -m governor status --run-id x",
            "python -m governor evaluate show --run-id x",
            "python -m governor plan resume --run-id x --approve --replace --force",
            "python -m governor dispatch --run-id x --approve --accept-failed-output",
        ]
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

        trace_path = run_dir / "trace.jsonl"
        events = [
            {
                "run_id": run_id,
                "event_id": "a1",
                "ts": "2026-05-25T12:01:00Z",
                "phase": "plan",
                "actor": "governor",
                "action": "plan_resume_start",
                "status": "ok",
            },
            {
                "run_id": run_id,
                "event_id": "a2",
                "ts": "2026-05-25T12:02:00Z",
                "phase": "plan",
                "actor": "governor",
                "action": "plan_resume_stop",
                "status": "pass",
            },
        ]
        with trace_path.open("w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

        ev_p = run_gov(["evaluate", "run", "--run-id", run_id, "--repo-path", rp], cwd=repo)
        if ev_p.returncode != 0:
            errors.append(f"evaluate run: {ev_p.stderr or ev_p.stdout}")

        eval_json = run_dir / "17_run_evaluation.json"
        eval_md = run_dir / "17_run_evaluation.md"
        if not eval_json.is_file() or not eval_md.is_file():
            errors.append("missing 17_run_evaluation artifacts")
        else:
            data = json.loads(eval_json.read_text(encoding="utf-8"))
            md = eval_md.read_text(encoding="utf-8")
            if data.get("gate_warn_count", 0) < 1:
                errors.append("gate_warn_count should include profile_compliance WARN")
            if data.get("human_decision_count", 0) < 1:
                errors.append("human_decision_count too low")
            if data.get("commands_executed_count", 0) < 3:
                errors.append("commands_executed_count wrong")
            if data.get("human_decision_count") == data.get("commands_executed_count"):
                errors.append("human_decision_count should not equal raw command count")
            if data.get("replace_flags_count", 0) < 1:
                errors.append("replace_flags_count missing")
            if data.get("active_execution_seconds") is None:
                errors.append("active_execution_seconds not set")
            if "fake-validator PASS is harness success" not in md:
                errors.append("markdown missing fake-validator caveat")
            if "profile compliance" not in md.lower():
                errors.append("markdown missing profile compliance note")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("EVALUATION ACCURACY SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
