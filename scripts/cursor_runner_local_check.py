#!/usr/bin/env python3
"""Optional local check for Cursor Headless executor setup (not mandatory CI)."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Cursor Headless runner local check")
    parser.add_argument(
        "--cursor-command",
        default="cursor",
        help="Cursor editor CLI on PATH",
    )
    parser.add_argument(
        "--agent-command",
        default="agent",
        help="Cursor Agent CLI on PATH (headless executor)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional .governor/config.json to inspect cursor-headless-local profile",
    )
    parser.add_argument(
        "--require",
        action="store_true",
        help="Exit 1 if cursor missing or profile disabled with empty argv",
    )
    args = parser.parse_args()

    lines: list[str] = []
    level = "OK"

    agent_path = shutil.which(args.agent_command)
    if not agent_path:
        lines.append(f"agent CLI not on PATH: {args.agent_command!r}")
        level = "WARN" if not args.require else "FAIL"
    else:
        lines.append(f"agent CLI found: {agent_path}")
        proc = subprocess.run(
            [args.agent_command, "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode == 0 and "--print" in (proc.stdout or ""):
            lines.append("agent --help: OK (use agent -p --force --output-format text; stdin prompt)")
        else:
            lines.append("agent --help: failed or missing -p flag")
            level = "WARN"

    if not shutil.which(args.cursor_command):
        lines.append(f"cursor editor CLI not on PATH: {args.cursor_command!r}")
    else:
        lines.append(f"cursor editor CLI found: {shutil.which(args.cursor_command)}")

    cfg_path = args.config or (ROOT / ".governor" / "config.json")
    if cfg_path.is_file():
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        prof = data.get("profiles", {}).get("cursor-headless-local", {})
        enabled = prof.get("enabled", False)
        argv = prof.get("argv") or []
        lines.append(f"profile cursor-headless-local: enabled={enabled} argv_len={len(argv)}")
        if enabled and not argv:
            lines.append("enabled but argv empty — unsafe")
            level = "FAIL" if args.require else "WARN"
        if not enabled:
            lines.append("profile disabled (expected until you verify headless argv)")
    else:
        lines.append(f"no local config at {cfg_path} (optional)")

    lines.append("Governor does not ship Cursor Headless argv — see docs/CURSOR_HEADLESS_RUNNER.md")

    label = f"CURSOR RUNNER CHECK {level}"
    print(label)
    for line in lines:
        print(f"  {line}")

    return 1 if level == "FAIL" and args.require else 0


if __name__ == "__main__":
    raise SystemExit(main())
