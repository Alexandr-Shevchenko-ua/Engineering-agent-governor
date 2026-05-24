#!/usr/bin/env python3
"""End-to-end smoke test for Engineering Agent Governor CLI."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_gov(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "governor", *args]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def main() -> int:
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "smoke@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Smoke Test"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# smoke\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        rp = str(repo)
        steps: list[tuple[str, list[str]]] = [
            ("init", ["init", "--task", "Smoke workflow", "--repo-path", rp]),
            ("status", ["status", "--repo-path", rp]),
            ("list", ["list", "--repo-path", rp]),
            ("doctor", ["doctor", "--repo-path", rp]),
        ]
        run_id: str | None = None
        for name, args in steps:
            proc = run_gov(args, ROOT)
            if proc.returncode != 0:
                errors.append(f"{name} failed: {proc.stderr or proc.stdout}")
            if name == "init":
                for line in proc.stdout.splitlines():
                    if line.startswith("Created run:"):
                        run_id = line.split(":", 1)[1].strip()
        if not run_id:
            errors.append("Could not parse run_id from init")
            print("\n".join(errors), file=sys.stderr)
            return 1

        exec_file = repo / "executor.md"
        exec_file.write_text("## Done\n", encoding="utf-8")
        val_file = repo / "validator.md"
        val_file.write_text("Verdict: PASS\n", encoding="utf-8")

        for name, args in [
            ("record executor", ["record", "--run-id", run_id, "--role", "executor", "--file", str(exec_file), "--repo-path", rp]),
            ("gate", ["gate", "--run-id", run_id, "--repo-path", rp]),
            ("record validator", ["record", "--run-id", run_id, "--role", "validator", "--file", str(val_file), "--repo-path", rp]),
            ("report", ["report", "--run-id", run_id, "--repo-path", rp]),
        ]:
            proc = run_gov(args, ROOT)
            if proc.returncode not in (0, 2) and name == "gate":
                errors.append(f"{name} failed: {proc.stderr or proc.stdout}")
            elif proc.returncode != 0 and name != "gate":
                errors.append(f"{name} failed: {proc.stderr or proc.stdout}")

        run_dir = repo / ".governor" / "runs" / run_id
        required = [
            "09_final_report.md",
            "10_lead_update.md",
            "08_gate_results.json",
            "05_executor_output.md",
            "06_validator_output.md",
        ]
        for name in required:
            if not (run_dir / name).exists():
                errors.append(f"Missing artifact: {name}")

        report = (run_dir / "09_final_report.md").read_text(encoding="utf-8")
        if "FINAL_REPORT_READY" not in report:
            errors.append("Final report missing FINAL_REPORT_READY state")

        index_file = repo / ".governor" / "index.json"
        if not index_file.exists():
            errors.append("Missing index.json")
        else:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            ids = [e["run_id"] for e in data.get("runs", [])]
            if run_id not in ids:
                errors.append(f"run_id {run_id} not in index.json")

    if errors:
        print("SMOKE FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
