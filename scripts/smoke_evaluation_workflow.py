#!/usr/bin/env python3
"""CI-safe smoke: v1.4.0 evaluation metrics workflow."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE_AGENT = ROOT / "scripts" / "fake_agent.py"


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
            ["git", "config", "user.email", "eval-smoke@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Eval Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# evaluation smoke\n", encoding="utf-8")
        (repo / ".gitignore").write_text(".governor/\n.claude/\n", encoding="utf-8")
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

        cfg_path = repo / ".governor" / "config.json"
        if cfg_path.is_file():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            for name in ("echo-test", "fake-validator"):
                if name in cfg.get("profiles", {}):
                    cfg["profiles"][name]["enabled"] = True
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

        init_p = run_gov(
            [
                "init",
                "--task",
                "Evaluation smoke task",
                "--policy",
                "default",
                "--repo-path",
                rp,
            ],
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
            errors.append("could not parse run_id from init")
            print("\n".join(errors), file=sys.stderr)
            return 1

        plan_p = run_gov(
            [
                "plan",
                "create",
                "--run-id",
                run_id,
                "--policy",
                "default",
                "--executor-profile",
                "echo-test",
                "--validator-profile",
                "fake-validator",
                "--repo-path",
                rp,
            ],
            cwd=repo,
        )
        if plan_p.returncode != 0:
            errors.append(f"plan create: {plan_p.stderr or plan_p.stdout}")

        run_dir = repo / ".governor" / "runs" / run_id
        (run_dir / "05_executor_output.md").write_text("executor ok\n", encoding="utf-8")
        (run_dir / "06_validator_output.md").write_text("## Verdict\n\nPASS\n", encoding="utf-8")
        (run_dir / "08_gate_results.json").write_text(
            json.dumps({"overall": "PASS", "changed_files_count": 1, "lines_added": 1, "lines_deleted": 0, "results": []})
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "09_final_report.md").write_text("# report\n", encoding="utf-8")

        for cmd in [
            ["evidence", "export", "--run-id", run_id, "--repo-path", rp],
            ["review", "export", "--run-id", run_id, "--repo-path", rp],
            ["evaluate", "run", "--run-id", run_id, "--repo-path", rp],
            [
                "evaluate",
                "annotate",
                "--run-id",
                run_id,
                "--repo-path",
                rp,
                "--manual-rework-minutes",
                "2",
                "--mr-outcome",
                "accepted",
                "--reviewer-burden-score",
                "2",
            ],
            ["evaluate", "export", "--repo-path", rp, "--format", "csv"],
            ["evaluate", "export", "--repo-path", rp, "--format", "markdown"],
            ["evaluate", "summary", "--repo-path", rp],
        ]:
            p = run_gov(cmd, cwd=repo)
            if p.returncode != 0:
                errors.append(f"{' '.join(cmd)}: {p.stderr or p.stdout}")

        required = [
            run_dir / "17_run_evaluation.json",
            run_dir / "17_run_evaluation.md",
            repo / ".governor" / "evaluations" / "evaluations.jsonl",
            repo / ".governor" / "evaluations" / "evaluations.csv",
            repo / ".governor" / "evaluations" / "evaluations.md",
        ]
        for path in required:
            if not path.is_file():
                errors.append(f"missing artifact: {path}")

        tracked = subprocess.run(
            ["git", "ls-files", ".governor"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if tracked.stdout.strip():
            errors.append(f".governor tracked in git: {tracked.stdout.strip()}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("EVALUATION SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
