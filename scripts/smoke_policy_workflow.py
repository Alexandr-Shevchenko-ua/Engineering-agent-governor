#!/usr/bin/env python3
"""Smoke: init --policy bugfix -> plan -> execute -> evidence."""

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
            ["git", "config", "user.email", "pol@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Policy Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# policy smoke\n", encoding="utf-8")
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
        proc = run_gov(
            [
                "init",
                "--task",
                "Fix run-id validation",
                "--policy",
                "bugfix",
                "--repo-path",
                rp,
            ]
        )
        if proc.returncode != 0:
            errors.append(f"init: {proc.stderr or proc.stdout}")
            return 1

        run_id = None
        for line in proc.stdout.splitlines():
            if line.startswith("Created run:"):
                run_id = line.split(":", 1)[1].strip()
        if not run_id:
            errors.append("no run_id")
            return 1
        if "Policy: bugfix" not in proc.stdout:
            errors.append("init should print Policy: bugfix")

        run_dir = repo / ".governor" / "runs" / run_id
        state = json.loads((run_dir / "run_state.json").read_text())
        if state.get("policy") != "bugfix":
            errors.append(f"policy not in run_state: {state.get('policy')}")

        intake = (run_dir / "00_task_intake.md").read_text(encoding="utf-8")
        if "bugfix" not in intake.lower():
            errors.append("intake not tailored to bugfix")

        create = run_gov(
            [
                "plan",
                "create",
                "--run-id",
                run_id,
                "--executor-profile",
                "echo-test",
                "--validator-profile",
                "fake-validator",
                "--repo-path",
                rp,
            ]
        )
        if create.returncode != 0:
            errors.append(f"plan create: {create.stderr or create.stdout}")

        plan = json.loads((run_dir / "12_run_plan.json").read_text())
        if not any(s.get("action") == "human_checkpoint" for s in plan["steps"]):
            errors.append("bugfix plan should include checkpoint after gate")

        exe = run_gov(
            [
                "plan",
                "execute",
                "--run-id",
                run_id,
                "--approve",
                "--continue-on-gate-warn",
                "--repo-path",
                rp,
            ]
        )
        if exe.returncode != 0 and "BLOCKED" not in (exe.stdout + exe.stderr):
            errors.append(f"plan execute: {exe.stderr or exe.stdout}")

        if exe.returncode != 0:
            cp = next(
                (s for s in plan["steps"] if s.get("action") == "human_checkpoint"),
                None,
            )
            if cp:
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
                        "plan",
                        "resume",
                        "--run-id",
                        run_id,
                        "--approve",
                        "--continue-on-gate-warn",
                        "--repo-path",
                        rp,
                    ]
                )
                if resume.returncode != 0:
                    errors.append(f"resume: {resume.stderr or resume.stdout}")

        ev = run_gov(["evidence", "export", "--run-id", run_id, "--repo-path", rp])
        if ev.returncode != 0:
            errors.append(f"evidence: {ev.stderr or ev.stdout}")

        bundle = json.loads((run_dir / "14_evidence_bundle.json").read_text())
        if bundle.get("policy") != "bugfix":
            errors.append("evidence missing policy")
        if "policy_compliance" not in bundle:
            errors.append("evidence missing policy_compliance")

        report = (run_dir / "09_final_report.md").read_text(encoding="utf-8")
        if "**Policy:**" not in report:
            errors.append("report missing policy section")

        state2 = json.loads((run_dir / "run_state.json").read_text())
        if state2.get("state") != "FINAL_REPORT_READY":
            errors.append(f"expected FINAL_REPORT_READY, got {state2.get('state')}")

        tracked = subprocess.run(
            ["git", "ls-files", ".governor"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if tracked.stdout.strip():
            errors.append(".governor tracked")

    if errors:
        print("POLICY SMOKE FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("POLICY SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
