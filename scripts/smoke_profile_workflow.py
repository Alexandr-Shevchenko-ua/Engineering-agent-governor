#!/usr/bin/env python3
"""Smoke test: governor config profiles + dispatch --profile workflow."""

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


def run_gov(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "governor", *args],
        cwd=cwd or ROOT,
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
            ["git", "config", "user.email", "profile@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Profile Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# profile smoke\n", encoding="utf-8")
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
        val = run_gov(["config", "validate", "--repo-path", rp])
        if val.returncode != 0:
            errors.append(f"config validate: {val.stderr or val.stdout}")
        if val.returncode not in (0,):
            pass

        proc = run_gov(["init", "--task", "Profile smoke", "--repo-path", rp])
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
                "--profile",
                "echo-test",
                "--repo-path",
                rp,
            ]
        )
        if preview.returncode != 0:
            errors.append(f"dispatch preview: {preview.stderr or preview.stdout}")
        if "Profile:" not in preview.stdout or "echo-test" not in preview.stdout:
            errors.append("preview missing profile name")

        run_dir = repo / ".governor" / "runs" / run_id
        if (run_dir / "05_executor_output.md").exists():
            errors.append("preview should not create executor output")

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
            ]
        )
        if exec_d.returncode != 0:
            errors.append(f"dispatch executor: {exec_d.stderr or exec_d.stdout}")

        gate = run_gov(["gate", "--run-id", run_id, "--repo-path", rp])
        if gate.returncode not in (0, 2):
            errors.append(f"gate: {gate.stderr or gate.stdout}")

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
            ]
        )
        if val_d.returncode != 0:
            errors.append(f"dispatch validator: {val_d.stderr or val_d.stdout}")

        report = run_gov(["report", "--run-id", run_id, "--repo-path", rp])
        if report.returncode != 0:
            errors.append(f"report: {report.stderr or report.stdout}")

        final = (run_dir / "09_final_report.md").read_text(encoding="utf-8")
        if "PASS" not in final and "Outcome: PASS" not in final:
            state = json.loads((run_dir / "run_state.json").read_text())
            if state.get("outcome") != "PASS":
                errors.append(f"expected PASS outcome, got {state.get('outcome')}")

        trace = (run_dir / "trace.jsonl").read_text()
        if "profile=echo-test" not in trace:
            errors.append("trace missing profile=echo-test")

        tracked = subprocess.run(
            ["git", "ls-files", ".governor"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if tracked.stdout.strip():
            errors.append(".governor tracked in temp repo")

    if errors:
        print("PROFILE SMOKE FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("PROFILE SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
