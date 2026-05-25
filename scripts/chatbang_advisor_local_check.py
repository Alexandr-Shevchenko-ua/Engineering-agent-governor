#!/usr/bin/env python3
"""Optional local check for chatbang + pexpect advisor bridge (not mandatory CI)."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governor.chatbang_bridge import (  # noqa: E402
    PEXPECT_INSTALL_HINT,
    is_chatbang_available,
    probe_chatbang,
    run_chatbang_once,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Chatbang advisor local check")
    parser.add_argument("--command", default="chatbang", help="Chatbang executable")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--require",
        action="store_true",
        help="Exit 1 on failure (default: warn only)",
    )
    parser.add_argument(
        "--use-fake",
        action="store_true",
        help="Test bridge with scripts/fake_chatbang.py instead of real chatbang",
    )
    args = parser.parse_args()

    import sys

    command = args.command
    if args.use_fake:
        command = f"{sys.executable} {ROOT / 'scripts' / 'fake_chatbang.py'}"

    lines: list[str] = []
    level = "OK"

    if not shutil.which(command.split()[0] if " " in command else command):
        lines.append(f"command not found: {command}")
        level = "FAIL"
    else:
        lines.append(f"command found: {command}")

    try:
        import pexpect  # noqa: F401
    except ImportError:
        lines.append(f"pexpect missing — {PEXPECT_INSTALL_HINT}")
        level = "FAIL"
    else:
        lines.append("pexpect import: OK")

    if level != "FAIL":
        if args.use_fake or is_chatbang_available(command):
            lines.append("availability: OK")
            probe = probe_chatbang(command=command, timeout=args.timeout)
            if probe.ok:
                lines.append("probe: OK")
            else:
                lines.append(f"probe: {probe.error or probe.status}")
                level = "WARN" if not args.require else "FAIL"
        else:
            lines.append("chatbang not available on PATH")
            level = "WARN" if not args.require else "FAIL"

    label = f"CHATBANG CHECK {level}"
    print(label)
    for line in lines:
        print(f"  {line}")

    if level == "FAIL" and args.require:
        return 1
    if level == "WARN" and args.require:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
