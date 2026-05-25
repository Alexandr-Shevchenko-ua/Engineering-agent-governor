#!/usr/bin/env python3
"""Smoke test: repair prepare -> dispatch repair -> gate -> validator -> report."""

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


def run_gov(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
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
            ["git", "config", "user.email", "repair@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Repair Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# repair smoke\n", encoding="utf-8")
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
        proc = run_gov(["init", "--task", "Repair smoke", "--repo-path", rp], cwd=repo)
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

        exec_d = run_gov(
            [
                "dispatch",
                "--run-id",
                run_id,
                "--role",
                "executor",
                "--profile",
                "echo-test",
                "--approve",
                "--repo-path",
                rp,
            ],
            cwd=repo,
        )
        if exec_d.returncode != 0:
            errors.append(f"executor: {exec_d.stderr or exec_d.stdout}")

        gate = run_gov(["gate", "--run-id", run_id, "--repo-path", rp], cwd=repo)
        if gate.returncode not in (0, 2):
            errors.append(f"gate: {gate.stderr or gate.stdout}")

        prep = run_gov(
            ["repair", "prepare", "--run-id", run_id, "--reason", "Smoke fix", "--repo-path", rp],
            cwd=repo,
        )
        if prep.returncode != 0:
            errors.append(f"repair prepare: {prep.stderr or prep.stdout}")

        run_dir = repo / ".governor" / "runs" / run_id
        if not (run_dir / "11_repair_prompt_1.md").is_file():
            errors.append("missing 11_repair_prompt_1.md")

        rep_d = run_gov(
            [
                "dispatch",
                "--run-id",
                run_id,
                "--role",
                "repair",
                "--profile",
                "echo-test",
                "--approve",
                "--repo-path",
                rp,
            ],
            cwd=repo,
        )
        if rep_d.returncode != 0:
            errors.append(f"repair dispatch: {rep_d.stderr or rep_d.stdout}")

        if not (run_dir / "07_repair_output_1.md").is_file():
            errors.append("missing 07_repair_output_1.md")

        gate2 = run_gov(["gate", "--run-id", run_id, "--repo-path", rp], cwd=repo)
        if gate2.returncode not in (0, 2):
            errors.append(f"gate2: {gate2.stderr or gate2.stdout}")

        val_d = run_gov(
            [
                "dispatch",
                "--run-id",
                run_id,
                "--role",
                "validator",
                "--profile",
                "fake-validator",
                "--approve",
                "--repo-path",
                rp,
            ],
            cwd=repo,
        )
        if val_d.returncode != 0:
            errors.append(f"validator: {val_d.stderr or val_d.stdout}")

        report = run_gov(["report", "--run-id", run_id, "--repo-path", rp], cwd=repo)
        if report.returncode != 0:
            errors.append(f"report: {report.stderr or report.stdout}")

        final = (run_dir / "09_final_report.md").read_text(encoding="utf-8")
        if "## Repair history" not in final:
            errors.append("report missing Repair history")

        trace = (run_dir / "trace.jsonl").read_text()
        if "repair_prepare" not in trace or "dispatch_repair" not in trace:
            errors.append("trace missing repair events")

        tracked = subprocess.run(
            ["git", "ls-files", ".governor"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if tracked.stdout.strip():
            errors.append(".governor tracked in temp repo")

    if errors:
        print("REPAIR SMOKE FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("REPAIR SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
