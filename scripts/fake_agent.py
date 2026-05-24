#!/usr/bin/env python3
"""Minimal fake agent for dispatch smoke tests — reads prompt stdin, writes markdown stdout."""

import sys

ROLE_HINT = "validator" if "validator" in sys.argv else "executor"

prompt = sys.stdin.read()
if ROLE_HINT == "validator" or "04_validator" in prompt or "Validator" in prompt:
    print("## Validator (fake_agent)\n\nVerdict: PASS\n")
else:
    print("## Executor (fake_agent)\n\n- Implemented smoke task\n- Commands: none\n")
