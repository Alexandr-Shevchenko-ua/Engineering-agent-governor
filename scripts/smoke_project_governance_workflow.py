#!/usr/bin/env python3
"""Smoke: project init, governed run with evidence + review package."""

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
        (repo / "README.md").write_text("# project governance smoke\n", encoding="utf-8")
        (repo / ".gitignore").write_text(".governor/\n", encoding="utf-8")
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

        rp = str(repo)
        for cmd in [
            ["project", "init", "--repo-path", rp],
            ["config", "init", "--repo-path", rp],
        ]:
            proc = run_gov(cmd)
            if proc.returncode != 0:
                errors.append(f"{cmd}: {proc.stderr or proc.stdout}")

        cfg_path = repo / ".governor" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["profiles"]["fake-validator"]["argv"] = [
            sys.executable,
            "scripts/fake_agent.py",
        ]
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

        proj = json.loads((repo / "governor.project.json").read_text(encoding="utf-8"))
        proj["gate_profiles"]["fast"] = {
            "description": "smoke fast",
            "commands": ["git_status_short", "git_diff_check", "diff_budget"],
            "required": ["git_diff_check"],
            "optional": ["diff_budget"],
        }
        (repo / "governor.project.json").write_text(
            json.dumps(proj, indent=2) + "\n",
            encoding="utf-8",
        )

        start = run_gov(
            [
                "run",
                "start",
                "--task",
                "Project governance smoke",
                "--policy",
                "default",
                "--use-default-profiles",
                "--approve",
                "--with-evidence",
                "--with-review-package",
                "--continue-on-gate-warn",
                "--repo-path",
                rp,
            ]
        )
        if start.returncode != 0:
            errors.append(f"run start: {start.stderr}\n{start.stdout}")

        runs = list((repo / ".governor" / "runs").glob("*"))
        if not runs:
            errors.append("no run folder created")
            print("\n".join(errors))
            return 1
        run_dir = runs[0]

        for name in (
            "09_final_report.md",
            "14_evidence_bundle.json",
            "15_review_package.md",
            "15_pr_body.md",
            "08_gate_results.json",
        ):
            if not (run_dir / name).is_file():
                errors.append(f"missing artifact: {name}")

        gate = json.loads((run_dir / "08_gate_results.json").read_text(encoding="utf-8"))
        if not gate.get("gate_profile"):
            errors.append("gate_profile missing in 08_gate_results.json")

        tracked = subprocess.run(
            ["git", "ls-files", ".governor"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if tracked.stdout.strip():
            errors.append(".governor is tracked in git")

    if errors:
        print("SMOKE FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("smoke_project_governance_workflow: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
