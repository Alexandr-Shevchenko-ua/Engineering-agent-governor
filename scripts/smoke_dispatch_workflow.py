#!/usr/bin/env python3
"""Smoke test: governor dispatch with echo + command fake_agent."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
            ["git", "config", "user.email", "dispatch@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Dispatch Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# dispatch smoke\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        rp = str(repo)
        proc = run_gov(["init", "--task", "Dispatch smoke", "--repo-path", rp])
        if proc.returncode != 0:
            errors.append(f"init: {proc.stderr or proc.stdout}")
            return 1

        run_id = None
        for line in proc.stdout.splitlines():
            if line.startswith("Created run:"):
                run_id = line.split(":", 1)[1].strip()
        if not run_id:
            errors.append("no run_id from init")
            return 1

        preview = run_gov(
            [
                "dispatch",
                "--run-id",
                run_id,
                "--role",
                "executor",
                "--runner",
                "echo",
                "--repo-path",
                rp,
            ]
        )
        if preview.returncode != 0:
            errors.append(f"dispatch preview: {preview.stderr or preview.stdout}")

        run_dir = repo / ".governor" / "runs" / run_id
        if (run_dir / "05_executor_output.md").exists():
            errors.append("preview should not create executor output")

        exec_dispatch = run_gov(
            [
                "dispatch",
                "--run-id",
                run_id,
                "--role",
                "executor",
                "--runner",
                "echo",
                "--approve",
                "--repo-path",
                rp,
            ]
        )
        if exec_dispatch.returncode != 0:
            errors.append(f"dispatch executor: {exec_dispatch.stderr or exec_dispatch.stdout}")

        gate = run_gov(["gate", "--run-id", run_id, "--repo-path", rp])
        if gate.returncode not in (0, 2):
            errors.append(f"gate: {gate.stderr or gate.stdout}")

        val_dispatch = run_gov(
            [
                "dispatch",
                "--run-id",
                run_id,
                "--role",
                "validator",
                "--runner",
                "command",
                "--approve",
                "--repo-path",
                rp,
                "--command",
                sys.executable,
                str(FAKE_AGENT),
            ]
        )
        if val_dispatch.returncode != 0:
            errors.append(f"dispatch validator: {val_dispatch.stderr or val_dispatch.stdout}")

        report = run_gov(["report", "--run-id", run_id, "--repo-path", rp])
        if report.returncode != 0:
            errors.append(f"report: {report.stderr or report.stdout}")

        final = (run_dir / "09_final_report.md").read_text(encoding="utf-8")
        if "FINAL_REPORT_READY" not in final:
            errors.append("missing FINAL_REPORT_READY in report")

        index = json.loads((repo / ".governor" / "index.json").read_text())
        if run_id not in [e["run_id"] for e in index.get("runs", [])]:
            errors.append("run missing from index.json")

        trace = (run_dir / "trace.jsonl").read_text()
        if "dispatch_preview" not in trace or "dispatch_executor" not in trace:
            errors.append("trace missing dispatch events")

    if errors:
        print("DISPATCH SMOKE FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("DISPATCH SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
