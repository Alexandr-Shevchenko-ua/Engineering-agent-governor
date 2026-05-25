#!/usr/bin/env python3
"""CI-safe smoke: cursor-auto Governor provider with fake cursor script."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "scripts" / "fake_cursor_governor.py"


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
            ["git", "config", "user.email", "cursorgov@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Cursor Gov Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# cursor governor smoke\n", encoding="utf-8")
        (repo / ".gitignore").write_text(".governor/\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        rp = str(repo)
        for cmd_args in [
            ["project", "init", "--repo-path", rp],
            ["config", "init", "--repo-path", rp],
        ]:
            p = run_gov(cmd_args, cwd=repo)
            if p.returncode != 0:
                errors.append(f"{' '.join(cmd_args)}: {p.stderr or p.stdout}")

        cfg_path = repo / ".governor" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg.setdefault("profiles", {})["cursor-governor-auto"] = {
            "runner": "command",
            "description": "Fake cursor governor for smoke",
            "argv": [
                sys.executable,
                str(FAKE),
                "--mode",
                "ask",
                "--model",
                "auto",
            ],
            "timeout": 120,
            "enabled": True,
        }
        for name in ("echo-test", "fake-validator"):
            if name in cfg.get("profiles", {}):
                cfg["profiles"][name]["enabled"] = True
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

        propose_p = run_gov(
            [
                "governor",
                "propose",
                "--task",
                "Cursor governor smoke task",
                "--provider",
                "cursor-auto",
                "--cursor-profile",
                "cursor-governor-auto",
                "--policy",
                "default",
                "--repo-path",
                rp,
            ],
            cwd=repo,
        )
        if propose_p.returncode != 0:
            errors.append(f"propose: {propose_p.stdout}\n{propose_p.stderr}")

        proposal_id = None
        for line in propose_p.stdout.splitlines():
            if line.startswith("Proposal:"):
                proposal_id = line.split(":", 1)[1].strip()
        if not proposal_id:
            errors.append("no proposal id from propose")
            _report(errors)
            return 1

        pj = repo / ".governor" / "proposals" / proposal_id / "proposal.json"
        data = json.loads(pj.read_text(encoding="utf-8"))
        if data.get("provider") != "cursor-auto":
            errors.append(f"expected provider cursor-auto, got {data.get('provider')}")
        if "PROVIDER_FAILED" in data.get("safety_flags", []):
            errors.append("unexpected PROVIDER_FAILED flag")

        val_p = run_gov(
            ["governor", "validate", "--proposal", proposal_id, "--repo-path", rp],
            cwd=repo,
        )
        if val_p.returncode != 0:
            errors.append(f"validate: {val_p.stdout}\n{val_p.stderr}")

        apply_p = run_gov(
            [
                "governor",
                "apply",
                "--proposal",
                proposal_id,
                "--approve",
                "--no-execute",
                "--repo-path",
                rp,
            ],
            cwd=repo,
        )
        if apply_p.returncode != 0:
            errors.append(f"apply: {apply_p.stdout}\n{apply_p.stderr}")

        run_id = None
        for line in apply_p.stdout.splitlines():
            if line.startswith("Created run:"):
                run_id = line.split(":", 1)[1].strip()
        if not run_id:
            errors.append("no run id from apply")
        else:
            run_dir = repo / ".governor" / "runs" / run_id
            if (run_dir / "05_executor_output.md").is_file():
                errors.append("executor ran unexpectedly")
            if not (run_dir / "12_run_plan.json").is_file():
                errors.append("12_run_plan.json not created")

        tracked = subprocess.run(
            ["git", "ls-files", ".governor"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
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
        print("CURSOR GOVERNOR PROVIDER SMOKE OK")


if __name__ == "__main__":
    raise SystemExit(main())
