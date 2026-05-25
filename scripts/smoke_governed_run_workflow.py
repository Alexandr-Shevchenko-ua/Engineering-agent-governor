#!/usr/bin/env python3
"""Smoke: governed run start (bugfix + checkpoint + resume) with evidence."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = ROOT / "examples" / "governor.config.example.json"
FAKE_AGENT = ROOT / "scripts" / "fake_agent.py"


def run_gov(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "governor", *args],
        cwd=ROOT,
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
            ["git", "config", "user.email", "gov@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Gov Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# governed smoke\n", encoding="utf-8")
        scripts_dir = repo / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(FAKE_AGENT, scripts_dir / "fake_agent.py")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        gov_dir = repo / ".governor"
        gov_dir.mkdir(parents=True, exist_ok=True)
        cfg = json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
        cfg["profiles"]["fake-validator"]["argv"] = [
            sys.executable,
            "scripts/fake_agent.py",
        ]
        (gov_dir / "config.json").write_text(
            json.dumps(cfg, indent=2) + "\n",
            encoding="utf-8",
        )

        rp = str(repo)
        start = run_gov(
            [
                "run",
                "start",
                "--task",
                "Governed smoke",
                "--policy",
                "bugfix",
                "--use-default-profiles",
                "--approve",
                "--with-evidence",
                "--repo-path",
                rp,
            ]
        )
        if start.returncode != 0:
            errors.append(f"run start: {start.stderr or start.stdout}")

        run_id = None
        for line in start.stdout.splitlines():
            if line.strip().startswith("Run ID:"):
                run_id = line.split(":", 1)[1].strip()
        if not run_id:
            errors.append("no run_id in summary")
            return 1

        run_dir = repo / ".governor" / "runs" / run_id
        state = json.loads((run_dir / "run_state.json").read_text())

        if state.get("state") != "FINAL_REPORT_READY":
            plan = json.loads((run_dir / "12_run_plan.json").read_text())
            cp = next(
                (s for s in plan["steps"] if s.get("action") == "human_checkpoint"),
                None,
            )
            if cp and cp.get("status") == "BLOCKED":
                approve = run_gov(
                    [
                        "plan",
                        "checkpoint",
                        "--run-id",
                        run_id,
                        "--step-id",
                        cp["step_id"],
                        "--approve",
                        "--note",
                        "Reviewed gate",
                        "--repo-path",
                        rp,
                    ]
                )
                if approve.returncode != 0:
                    errors.append(f"checkpoint: {approve.stderr}")
                resume = run_gov(
                    [
                        "run",
                        "resume",
                        "--run-id",
                        run_id,
                        "--approve",
                        "--with-evidence",
                        "--repo-path",
                        rp,
                    ]
                )
                if resume.returncode != 0:
                    errors.append(f"run resume: {resume.stderr or resume.stdout}")
                state = json.loads((run_dir / "run_state.json").read_text())

        if not (run_dir / "12_run_plan.json").is_file():
            errors.append("missing plan")
        if not (run_dir / "05_executor_output.md").is_file():
            errors.append("missing executor output")
        if not (run_dir / "08_gate_results.json").is_file():
            errors.append("missing gate")
        if not (run_dir / "06_validator_output.md").is_file():
            errors.append("missing validator")
        if state.get("state") != "FINAL_REPORT_READY":
            errors.append(f"state {state.get('state')}")
        if state.get("outcome") != "PASS":
            errors.append(f"outcome {state.get('outcome')}")
        if not (run_dir / "09_final_report.md").is_file():
            errors.append("missing report")
        if not (run_dir / "14_evidence_bundle.json").is_file():
            errors.append("missing evidence")
        report = (run_dir / "09_final_report.md").read_text(encoding="utf-8")
        if "**Policy:**" not in report:
            errors.append("report missing policy")

        tracked = subprocess.run(
            ["git", "ls-files", ".governor"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if tracked.stdout.strip():
            errors.append(".governor tracked")

    if errors:
        print("GOVERNED RUN SMOKE FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("GOVERNED RUN SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
