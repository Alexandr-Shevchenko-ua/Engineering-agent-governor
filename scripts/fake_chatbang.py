#!/usr/bin/env python3
"""Fake interactive chatbang for CI — prints prompt, reads lines, echoes advisor-style replies."""

from __future__ import annotations

import sys


def main() -> None:
    sys.stdout.write("> ")
    sys.stdout.flush()
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        msg = line.strip()
        if not msg:
            sys.stdout.write("> ")
            sys.stdout.flush()
            continue
        if "CHATBANG_OK" in msg.upper():
            sys.stdout.write("CHATBANG_OK\n")
        else:
            sys.stdout.write(f"ADVISOR: acknowledged ({len(msg)} chars in prompt)\n")
        sys.stdout.write("> ")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
