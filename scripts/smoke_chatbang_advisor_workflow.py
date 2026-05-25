#!/usr/bin/env python3
"""CI-safe smoke: advisor ask with fake interactive chatbang (not real chatbang)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE_CHATBANG = ROOT / "scripts" / "fake_chatbang.py"


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
            ["git", "config", "user.email", "advisor@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Advisor Smoke"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        (repo / "README.md").write_text("# advisor smoke\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        rp = str(repo)
        init_p = run_gov(
            ["init", "--task", "Advisor smoke", "--policy", "default", "--repo-path", rp]
        )
        if init_p.returncode != 0:
            errors.append(f"init: {init_p.stderr or init_p.stdout}")
            _report(errors)
            return 1

        run_id = None
        for line in init_p.stdout.splitlines():
            if line.startswith("Created run:"):
                run_id = line.split(":", 1)[1].strip()
        if not run_id:
            errors.append("no run id from init")
            _report(errors)
            return 1

        state_before = json.loads(
            (repo / ".governor" / "runs" / run_id / "run_state.json").read_text(encoding="utf-8")
        )["state"]

        fake_cmd = f"{sys.executable} {FAKE_CHATBANG}"
        ask_p = run_gov(
            [
                "advisor",
                "ask",
                "--run-id",
                run_id,
                "--provider",
                "chatbang",
                "--kind",
                "next-action",
                "--chatbang-command",
                fake_cmd,
                "--timeout",
                "30",
                "--repo-path",
                rp,
            ]
        )
        if ask_p.returncode != 0:
            errors.append(f"advisor ask: {ask_p.stdout}\n{ask_p.stderr}")

        run_dir = repo / ".governor" / "runs" / run_id
        for name in ("16_advisor_request_1.md", "16_advisor_response_1.md"):
            if not (run_dir / name).is_file():
                errors.append(f"missing {name}")

        trace = run_dir / "trace.jsonl"
        if trace.is_file():
            found = False
            for line in trace.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    ev = json.loads(line)
                    if ev.get("phase") == "advisor" and "advisor_chatbang" in ev.get("action", ""):
                        found = True
            if not found:
                errors.append("no advisor trace event")
        else:
            errors.append("missing trace.jsonl")

        state_after = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))["state"]
        if state_after != state_before:
            errors.append(f"state changed: {state_before} -> {state_after}")

    _report(errors)
    return 0 if not errors else 1


def _report(errors: list[str]) -> None:
    if errors:
        print("CHATBANG ADVISOR SMOKE FAILED:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("CHATBANG ADVISOR SMOKE OK")


if __name__ == "__main__":
    raise SystemExit(main())
