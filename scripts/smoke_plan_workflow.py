#!/usr/bin/env python3
"""Smoke test: plan create -> show -> execute --approve -> PASS."""

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
            ["git", "config", "user.email", "plan@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Plan Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# plan smoke\n", encoding="utf-8")
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
        proc = run_gov(["init", "--task", "Plan smoke", "--repo-path", rp])
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
                "--repo-path",
                rp,
            ]
        )
        if create.returncode != 0:
            errors.append(f"plan create: {create.stderr or create.stdout}")

        show = run_gov(["plan", "show", "--run-id", run_id, "--repo-path", rp])
        if show.returncode != 0:
            errors.append(f"plan show: {show.stderr or show.stdout}")

        run_dir = repo / ".governor" / "runs" / run_id
        if not (run_dir / "12_run_plan.json").is_file():
            errors.append("missing 12_run_plan.json")

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
        if exe.returncode != 0:
            errors.append(f"plan execute: {exe.stderr or exe.stdout}")

        state = json.loads((run_dir / "run_state.json").read_text())
        if state.get("state") != "FINAL_REPORT_READY":
            errors.append(f"expected FINAL_REPORT_READY, got {state.get('state')}")
        if state.get("outcome") != "PASS":
            errors.append(f"expected PASS outcome, got {state.get('outcome')}")

        final = (run_dir / "09_final_report.md").read_text(encoding="utf-8")
        if "## Run plan" not in final:
            errors.append("report missing Run plan section")

        trace = (run_dir / "trace.jsonl").read_text()
        if "plan_create" not in trace or "plan_execute_start" not in trace:
            errors.append("trace missing plan events")

        tracked = subprocess.run(
            ["git", "ls-files", ".governor"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if tracked.stdout.strip():
            errors.append(".governor tracked")

    if errors:
        print("PLAN SMOKE FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("PLAN SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
