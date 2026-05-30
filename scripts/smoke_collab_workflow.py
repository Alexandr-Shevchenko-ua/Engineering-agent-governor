#!/usr/bin/env python3
"""CI-safe smoke: collab loop with fake chatbang and echo-test executor."""

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
            ["git", "config", "user.email", "collab@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Collab Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# collab smoke\n", encoding="utf-8")
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
        start_p = run_gov(
            [
                "collab",
                "start",
                "--task",
                "Collab smoke workflow",
                "--max-rounds",
                "2",
                "--executor-profile",
                "echo-test",
                "--commit-policy",
                "never",
                "--chatbang-command",
                fake_cmd,
                "--chatbang-timeout",
                "60",
                "--approve",
                "--repo-path",
                rp,
            ],
            cwd=repo,
        )
        if start_p.returncode != 0:
            errors.append(f"collab start: {start_p.stderr or start_p.stdout}")

        list_p = run_gov(["collab", "list", "--repo-path", rp], cwd=repo)
        if list_p.returncode != 0:
            errors.append(f"collab list: {list_p.stderr or list_p.stdout}")

    if errors:
        print("smoke_collab_workflow FAILED:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print("smoke_collab_workflow OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
