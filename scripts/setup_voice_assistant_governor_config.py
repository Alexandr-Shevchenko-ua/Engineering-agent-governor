#!/usr/bin/env python3
"""Write .governor/config.json for voice_assistant repo (cursor agent + chatbang paths)."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-path",
        required=True,
        help="voice_assistant repo root (contains .governor/)",
    )
    parser.add_argument("--agent-command", default="agent")
    args = parser.parse_args()

    repo = Path(args.repo_path).resolve()
    cfg_path = repo / ".governor" / "config.json"
    if not cfg_path.is_file():
        print(f"Missing {cfg_path}; run: python -m governor config init --repo-path {repo}")
        return 1

    agent = shutil.which(args.agent_command) or args.agent_command
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    profiles = data.setdefault("profiles", {})

    profiles["cursor-headless-local"] = {
        "runner": "command",
        "description": "Cursor Agent headless executor (prompt on stdin)",
        "argv": [agent, "-p", "--force", "--output-format", "text"],
        "timeout": 1800,
        "enabled": True,
    }
    profiles["echo-test"] = profiles.get(
        "echo-test",
        {
            "runner": "echo",
            "description": "Safe echo runner",
            "timeout": 300,
            "enabled": True,
        },
    )
    profiles["echo-test"]["enabled"] = True

    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Updated {cfg_path}")
    print(f"  cursor-headless-local.argv = {[agent, '-p', '--force', '--output-format', 'text']}")
    print("Next:")
    print(f"  python -m governor config validate --repo-path {repo}")
    print(f"  python scripts/cursor_runner_local_check.py --config {cfg_path} --require")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
