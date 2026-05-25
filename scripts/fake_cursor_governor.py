#!/usr/bin/env python3
"""Fake Cursor Headless Governor provider for CI — reads stdin, prints proposal JSON."""

from __future__ import annotations

import json
import sys


def _governor_proposal_json(task_hint: str = "smoke task") -> str:
    payload = {
        "task": task_hint,
        "recommended_policy": "default",
        "assumptions": ["Fake cursor-auto Governor proposal for CI"],
        "risk_register": ["Synthetic proposal — not production advice"],
        "acceptance_criteria": ["pytest passes", "governor check passes"],
        "executor_prompt": f"# Executor\n\nImplement bounded task: {task_hint}",
        "validator_prompt": f"# Validator\n\nValidate task: {task_hint}",
        "recommended_plan": [
            {
                "step_id": "1",
                "action": "dispatch_executor",
                "description": "Executor via profile",
            },
            {"step_id": "2", "action": "gate", "description": "Run gates"},
            {
                "step_id": "3",
                "action": "dispatch_validator",
                "description": "Validator review",
            },
        ],
        "recommended_profiles": {
            "executor": "echo-test",
            "validator": "fake-validator",
        },
        "stop_conditions": ["Stop on gate FAIL"],
        "required_human_decisions": ["Approve apply", "Approve dispatch"],
        "confidence": "MEDIUM",
    }
    return (
        "Cursor Governor proposal (fake).\n\n"
        f"```json\n{json.dumps(payload, indent=2)}\n```\n"
    )


def _probe_ok() -> str:
    return json.dumps({"status": "CURSOR_GOVERNOR_OK"}) + "\n"


def main() -> None:
    if "--fail" in sys.argv:
        sys.stderr.write("fake cursor governor forced failure\n")
        sys.exit(1)
    text = sys.stdin.read()
    if "CURSOR_GOVERNOR_OK" in text or '"status"' in text:
        sys.stdout.write(_probe_ok())
        return
    task = "smoke task"
    for line in text.splitlines():
        if line.strip().startswith("Task:"):
            task = line.split("Task:", 1)[1].strip()[:120]
            break
        if line.strip().startswith("## Task"):
            continue
    if "## Task" in text:
        for part in text.split("## Task", 1)[1].splitlines():
            part = part.strip()
            if part and not part.startswith("#"):
                task = part[:120]
                break
    sys.stdout.write(_governor_proposal_json(task))


if __name__ == "__main__":
    main()
