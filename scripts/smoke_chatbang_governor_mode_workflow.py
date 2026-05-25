#!/usr/bin/env python3
"""CI-safe smoke: Chatbang Governor Mode with fake chatbang (no real chatbang)."""

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
            ["git", "config", "user.email", "govmode@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Gov Mode Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# governor mode smoke\n", encoding="utf-8")
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
        if cfg_path.is_file():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            for name in ("echo-test", "fake-validator"):
                if name in cfg.get("profiles", {}):
                    cfg["profiles"][name]["enabled"] = True
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

        fake_cmd = f"{sys.executable} {FAKE}"
        propose_p = run_gov(
            [
                "governor",
                "propose",
                "--task",
                "Governor mode smoke task",
                "--chatbang-command",
                fake_cmd,
                "--timeout",
                "60",
                "--repo-path",
                rp,
            ],
            cwd=repo,
        )
        if propose_p.returncode != 0:
            errors.append(f"propose: {propose_p.stdout}\n{propose_p.stderr}")
            _report(errors)
            return 1

        proposal_id = None
        for line in propose_p.stdout.splitlines():
            if line.startswith("Proposal:"):
                proposal_id = line.split(":", 1)[1].strip()
        if not proposal_id:
            errors.append("no proposal id from propose")
            _report(errors)
            return 1

        pdir = repo / ".governor" / "proposals" / proposal_id
        for name in ("proposal.json", "proposal.md", "raw_chatbang_response.md", "trace.jsonl"):
            if not (pdir / name).is_file():
                errors.append(f"missing {name}")

        val_p = run_gov(
            ["governor", "validate", "--proposal", proposal_id, "--repo-path", rp],
            cwd=repo,
        )
        if val_p.returncode != 0:
            errors.append(f"validate: {val_p.stdout}")

        show_p = run_gov(
            ["governor", "show", "--proposal", proposal_id, "--repo-path", rp],
            cwd=repo,
        )
        if show_p.returncode != 0:
            errors.append(f"show: {show_p.stderr}")

        apply_p = run_gov(
            [
                "governor",
                "apply",
                "--proposal",
                proposal_id,
                "--approve",
                "--repo-path",
                rp,
            ],
            cwd=repo,
        )
        if apply_p.returncode != 0:
            errors.append(f"apply: {apply_p.stdout}\n{apply_p.stderr}")

        pdata = json.loads((pdir / "proposal.json").read_text(encoding="utf-8"))
        if pdata.get("status") != "APPLIED":
            errors.append(f"proposal status not APPLIED: {pdata.get('status')}")
        run_id = pdata.get("applied_run_id")
        if not run_id:
            errors.append("no applied_run_id")
        else:
            run_dir = repo / ".governor" / "runs" / run_id
            if not (run_dir / "12_run_plan.json").is_file():
                errors.append("missing 12_run_plan.json")
            if (run_dir / "05_executor_output.md").is_file():
                errors.append("executor ran unexpectedly")
            if not (run_dir / "00_governor_proposal_ref.json").is_file():
                errors.append("missing proposal ref on run")

        tracked = subprocess.run(
            ["git", "ls-files", ".governor"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if tracked.stdout.strip():
            errors.append("ROOT repo tracks .governor (expected ignored)")

    _report(errors)
    return 0 if not errors else 1


def _report(errors: list[str]) -> None:
    if errors:
        print("CHATBANG GOVERNOR MODE SMOKE FAILED:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("CHATBANG GOVERNOR MODE SMOKE OK")


if __name__ == "__main__":
    raise SystemExit(main())
