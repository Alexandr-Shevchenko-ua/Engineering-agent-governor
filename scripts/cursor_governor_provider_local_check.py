#!/usr/bin/env python3
"""Local check for cursor-governor-auto profile (no Cursor required by default)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from governor.config import config_path, load_profiles
from governor.governor_providers import (
    DEFAULT_CURSOR_GOVERNOR_PROFILE,
    argv_has_ask_mode,
    validate_cursor_governor_profile,
)
from governor.utils import resolve_repo_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-path", default=".", help="Repository path")
    parser.add_argument(
        "--require",
        action="store_true",
        help="Exit non-zero if cursor-governor-auto profile missing",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Run fake or configured argv with harmless probe prompt",
    )
    args = parser.parse_args()
    repo = resolve_repo_path(args.repo_path)
    cfg = config_path(repo)
    warnings: list[str] = []
    errors: list[str] = []

    if not cfg.is_file():
        msg = f"No config at {cfg} — run: python -m governor config init --repo-path ."
        if args.require:
            print(msg, file=sys.stderr)
            return 1
        print(f"WARN: {msg}")
        return 0

    profiles = load_profiles(cfg)
    name = DEFAULT_CURSOR_GOVERNOR_PROFILE
    if name not in profiles:
        msg = f"Profile {name!r} not in {cfg}"
        if args.require:
            print(f"FAIL: {msg}", file=sys.stderr)
            return 1
        print(f"WARN: {msg}")
        return 0

    spec = profiles[name]
    if spec.runner != "command":
        errors.append(f"Profile must use runner 'command', got {spec.runner!r}")
    if not spec.argv:
        warnings.append("Profile argv is empty — fill locally before cursor-auto propose")
    elif not argv_has_ask_mode(spec.argv):
        warnings.append("Profile argv lacks --mode ask (Governor must be read-only)")
    else:
        try:
            validate_cursor_governor_profile(spec)
            print(f"OK: profile {name!r} argv looks read-only")
        except ValueError as e:
            errors.append(str(e))

    if not spec.enabled:
        warnings.append(f"Profile {name!r} is disabled (enable locally or use --allow-disabled-profile)")

    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"FAIL: {e}", file=sys.stderr)

    if args.probe and spec.argv:
        fake = ROOT / "scripts" / "fake_cursor_governor.py"
        argv = spec.argv
        if not spec.enabled and str(fake) in " ".join(argv):
            pass
        probe_argv = list(argv)
        if str(ROOT) not in " ".join(probe_argv):
            probe_argv = [sys.executable, str(fake), "--mode", "ask"]
        proc = subprocess.run(
            probe_argv,
            input='Return exactly CURSOR_GOVERNOR_OK in JSON field "status".\n',
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            errors.append(f"Probe exit {proc.returncode}")
        elif "CURSOR_GOVERNOR_OK" not in out:
            errors.append("Probe did not return CURSOR_GOVERNOR_OK")
        else:
            print("OK: probe returned CURSOR_GOVERNOR_OK")

    if errors:
        return 1
    if not warnings:
        print("CURSOR GOVERNOR LOCAL CHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
