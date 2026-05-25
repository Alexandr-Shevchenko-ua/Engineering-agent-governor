#!/usr/bin/env python3
"""Safe local release validation for Engineering Agent Governor (no dirty repo)."""

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


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    errors: list[str] = []

    ver = run([sys.executable, "-m", "governor", "version"])
    if ver.returncode != 0:
        errors.append(f"version command failed: {ver.stderr}")
    elif "1.3.0" not in (ver.stdout or ""):
        errors.append(f"unexpected version output: {ver.stdout.strip()}")

    val = run([sys.executable, "-m", "governor", "project", "validate", "--repo-path", str(ROOT)])
    if val.returncode != 0:
        errors.append(f"project validate failed:\n{val.stdout}")

    ignore = run(["git", "check-ignore", ".governor/config.json"], cwd=ROOT)
    if ignore.returncode != 0:
        errors.append(".governor/config.json is not gitignored")

    tracked = run(["git", "ls-files", ".governor"], cwd=ROOT)
    if tracked.stdout.strip():
        errors.append(f".governor has tracked files: {tracked.stdout.strip()[:200]}")

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "release@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Release Check"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# release check\n", encoding="utf-8")
        (repo / ".gitignore").write_text(".governor/\n", encoding="utf-8")
        (repo / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy(FAKE_AGENT, repo / "scripts" / "fake_agent.py")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        rp = str(repo)
        for args in [
            ["project", "init", "--repo-path", rp],
            ["config", "init", "--repo-path", rp],
        ]:
            p = run([sys.executable, "-m", "governor", *args])
            if p.returncode != 0:
                errors.append(f"governor {' '.join(args)}: {p.stderr}")

        cfg_path = repo / ".governor" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["profiles"]["fake-validator"]["argv"] = [
            sys.executable,
            "scripts/fake_agent.py",
        ]
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

        proj = json.loads((repo / "governor.project.json").read_text(encoding="utf-8"))
        proj["gate_profiles"]["fast"] = {
            "description": "release check",
            "commands": ["git_status_short", "git_diff_check"],
            "required": ["git_diff_check"],
            "optional": [],
        }
        (repo / "governor.project.json").write_text(
            json.dumps(proj, indent=2) + "\n",
            encoding="utf-8",
        )

        start = run(
            [
                sys.executable,
                "-m",
                "governor",
                "run",
                "start",
                "--task",
                "Self dogfood release",
                "--policy",
                "default",
                "--use-default-profiles",
                "--approve",
                "--with-evidence",
                "--with-review-package",
                "--repo-path",
                rp,
            ]
        )
        if start.returncode != 0:
            errors.append(f"governed run failed:\n{start.stdout}\n{start.stderr}")

        runs = list((repo / ".governor" / "runs").glob("*"))
        if not runs:
            errors.append("no run folder in temp repo")
        else:
            run_dir = runs[0]
            for name in (
                "09_final_report.md",
                "14_evidence_bundle.json",
                "15_review_package.md",
                "15_pr_body.md",
            ):
                if not (run_dir / name).is_file():
                    errors.append(f"missing {name} in temp run")

    if errors:
        print("SELF DOGFOOD FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("SELF DOGFOOD OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
