#!/usr/bin/env python3
"""CI-safe smoke: v1.3.1 stabilization (safety audit, diagnose, cleanup)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "scripts" / "fake_chatbang.py"


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
            ["git", "config", "user.email", "stab@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Stab Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# stabilization smoke\n", encoding="utf-8")
        (repo / ".gitignore").write_text(".governor/\n.claude/\n", encoding="utf-8")
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
                "Stabilization smoke",
                "--policy",
                "default",
                "--repo-path",
                rp,
            ],
            cwd=repo,
        )
        if init_p.returncode != 0:
            errors.append(f"init: {init_p.stdout}\n{init_p.stderr}")
            _report(errors)
            return 1

        run_id = None
        for line in init_p.stdout.splitlines():
            if line.startswith("Created run:") or line.startswith("Run ID:"):
                run_id = line.split(":", 1)[1].strip()
        if not run_id:
            runs = sorted(
                (p for p in (repo / ".governor" / "runs").iterdir() if p.is_dir()),
                key=lambda p: p.name,
            )
            if runs:
                run_id = runs[-1].name
        if not run_id:
            errors.append("no run id from init")
            _report(errors)
            return 1

        plan_p = run_gov(
            [
                "plan",
                "create",
                "--run-id",
                run_id,
                "--policy",
                "default",
                "--gate-profile",
                "fast",
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
            errors.append(f"plan create: {plan_p.stdout}\n{plan_p.stderr}")

        audit_p = run_gov(["safety", "audit", "--repo-path", rp], cwd=repo)
        if audit_p.returncode != 0:
            errors.append(f"safety audit: {audit_p.stdout}\n{audit_p.stderr}")

        diag_p = run_gov(
            ["diagnose", "--run-id", run_id, "--repo-path", rp],
            cwd=repo,
        )
        if diag_p.returncode != 0:
            errors.append(f"diagnose: {diag_p.stdout}\n{diag_p.stderr}")

        for sub in ("status",):
            st_p = run_gov(["cleanup", sub, "--repo-path", rp], cwd=repo)
            if st_p.returncode != 0:
                errors.append(f"cleanup {sub}: {st_p.stderr}")

        for sub in ("runs", "proposals"):
            cl_p = run_gov(
                ["cleanup", sub, "--repo-path", rp, "--keep-last", "5", "--dry-run"],
                cwd=repo,
            )
            if cl_p.returncode != 0:
                errors.append(f"cleanup {sub} dry-run: {cl_p.stderr}")

        tracked = subprocess.run(
            ["git", "ls-files", ".governor"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if tracked.stdout.strip():
            errors.append(f".governor tracked: {tracked.stdout.strip()}")

    _report(errors)
    return 0 if not errors else 1


def _report(errors: list[str]) -> None:
    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
    else:
        print("STABILIZATION SMOKE OK")


if __name__ == "__main__":
    raise SystemExit(main())
