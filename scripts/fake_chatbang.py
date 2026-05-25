#!/usr/bin/env python3
"""Fake interactive chatbang for CI — advisor ack or Governor proposal JSON."""

from __future__ import annotations

import json
import sys


def _governor_proposal_json(task_hint: str = "smoke task") -> str:
    payload = {
        "task": task_hint,
        "recommended_policy": "default",
        "assumptions": ["Fake chatbang proposal for CI smoke"],
        "risk_register": ["Synthetic proposal — not production advice"],
        "acceptance_criteria": ["pytest passes", "governor check passes"],
        "executor_prompt": f"Implement bounded task: {task_hint}",
        "validator_prompt": f"Validate task: {task_hint}",
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
        "Chatbang Governor proposal (fake).\n\n"
        f"```json\n{json.dumps(payload, indent=2)}\n```\n"
    )


def main() -> None:
    sys.stdout.write("> ")
    sys.stdout.flush()
    buffer: list[str] = []
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        buffer.append(line)
        msg = line.strip()
        text = "".join(buffer)
        if "GOVERNOR_MODE_OK" in msg.upper() or (
            "GOVERNOR_MODE" in msg.upper() and "ACKNOWLEDGE" in text.upper()
        ):
            sys.stdout.write("GOVERNOR_MODE_OK\n")
            buffer.clear()
        elif "CHATBANG_OK" in msg.upper() and "GOVERNOR_MODE" not in text:
            sys.stdout.write("CHATBANG_OK\n")
            buffer.clear()
        elif (
            "GOVERNOR_MODE_V12" in text
            or "GOVERNOR_MODE_V12" in line
            or "Chatbang Governor" in line
            or "Chatbang Governor" in text
            or "output proposal JSON" in text.lower()
        ):
            task = "smoke task"
            for part in text.splitlines():
                line = part.strip()
                if line.startswith("Task:"):
                    task = line.split("Task:", 1)[1].strip()[:120]
                    break
            if task == "smoke task" and "## Task" in text:
                for part in text.split("## Task", 1)[1].splitlines():
                    part = part.strip()
                    if part and not part.startswith("#"):
                        task = part[:120]
                        break
            sys.stdout.write(_governor_proposal_json(task))
            buffer.clear()
        elif not msg and buffer:
            continue
        elif msg and "Chatbang Governor" not in text and len(buffer) == 1:
            sys.stdout.write(f"ADVISOR: acknowledged ({len(msg)} chars in prompt)\n")
            buffer.clear()
        sys.stdout.write("> ")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
