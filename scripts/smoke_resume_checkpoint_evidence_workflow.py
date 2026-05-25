#!/usr/bin/env python3
"""Smoke: checkpoint after gate -> approve -> resume -> evidence export."""

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
            ["git", "config", "user.email", "v06@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "V06 Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# v06 smoke\n", encoding="utf-8")
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
        proc = run_gov(["init", "--task", "V06 checkpoint smoke", "--repo-path", rp])
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
                "--checkpoint-after",
                "gate",
                "--checkpoint",
                "Review gate results before validator",
                "--repo-path",
                rp,
            ]
        )
        if create.returncode != 0:
            errors.append(f"plan create: {create.stderr or create.stdout}")

        exe = run_gov(
            [
                "plan",
                "execute",
                "--run-id",
                run_id,
                "--approve",
                "--repo-path",
                rp,
            ]
        )
        if exe.returncode == 0:
            errors.append("execute should stop at checkpoint (non-zero exit)")

        run_dir = repo / ".governor" / "runs" / run_id
        plan = json.loads((run_dir / "12_run_plan.json").read_text())
        cp = next(s for s in plan["steps"] if s["action"] == "human_checkpoint")
        if cp.get("status") != "BLOCKED":
            errors.append(f"checkpoint not BLOCKED: {cp.get('status')}")

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
                "Reviewed gate results",
                "--repo-path",
                rp,
            ]
        )
        if approve.returncode != 0:
            errors.append(f"checkpoint approve: {approve.stderr or approve.stdout}")

        if not (run_dir / "13_human_checkpoints.md").is_file():
            errors.append("missing 13_human_checkpoints.md")

        resume = run_gov(
            [
                "plan",
                "resume",
                "--run-id",
                run_id,
                "--approve",
                "--repo-path",
                rp,
            ]
        )
        if resume.returncode != 0:
            errors.append(f"plan resume: {resume.stderr or resume.stdout}")

        ev = run_gov(
            ["evidence", "export", "--run-id", run_id, "--repo-path", rp]
        )
        if ev.returncode != 0:
            errors.append(f"evidence export: {ev.stderr or ev.stdout}")

        state = json.loads((run_dir / "run_state.json").read_text())
        if state.get("state") != "FINAL_REPORT_READY":
            errors.append(f"expected FINAL_REPORT_READY, got {state.get('state')}")
        if state.get("outcome") != "PASS":
            errors.append(f"expected PASS, got {state.get('outcome')}")

        plan2 = json.loads((run_dir / "12_run_plan.json").read_text())
        cp2 = next(s for s in plan2["steps"] if s["action"] == "human_checkpoint")
        if cp2.get("status") != "PASS":
            errors.append("checkpoint not PASS after approve")

        if not (run_dir / "14_evidence_bundle.md").is_file():
            errors.append("missing 14_evidence_bundle.md")
        if not (run_dir / "14_evidence_bundle.json").is_file():
            errors.append("missing 14_evidence_bundle.json")

        trace = (run_dir / "trace.jsonl").read_text()
        if "human_checkpoint_approve" not in trace:
            errors.append("trace missing human_checkpoint_approve")
        if "evidence_export" not in trace:
            errors.append("trace missing evidence_export")

        tracked = subprocess.run(
            ["git", "ls-files", ".governor"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if tracked.stdout.strip():
            errors.append(".governor tracked")

    if errors:
        print("V06 SMOKE FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("V06 SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
