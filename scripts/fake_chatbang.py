#!/usr/bin/env python3
"""Fake interactive chatbang for CI — advisor ack or Governor proposal JSON."""

from __future__ import annotations

import json
import re
import sys



def _collab_json(task_hint: str = "collab task", *, source_text: str = "") -> str:
    """Return CONTINUE or PASS based on round markers in the Governor message."""
    if "Формат відхилено" in source_text:
        payload = {
            "verdict": "CONTINUE",
            "summary": f"Fake collab format retry for: {task_hint}",
            "next_executor_prompt": (
                f"# Executor\n\nImplement bounded collab task (retry): {task_hint}\n"
            ),
            "stop_reason": None,
        }
    else:
        round_m = re.search(r"Раунд\s+(\d+)\s+з\s+(\d+)", source_text)
        if round_m and int(round_m.group(1)) >= int(round_m.group(2)):
            payload = {
                "verdict": "PASS",
                "summary": f"Fake collab done for: {task_hint}",
                "next_executor_prompt": "",
                "stop_reason": None,
            }
        else:
            payload = {
                "verdict": "CONTINUE",
                "summary": f"Fake collab: implement slice for {task_hint}",
                "next_executor_prompt": (
                    f"# Executor\n\nImplement bounded collab task: {task_hint}\n"
                ),
                "stop_reason": None,
            }
    return (
        "Chatbang collab review (fake).\n\n"
        f"```json\n{json.dumps(payload, indent=2)}\n```\n"
    )


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


def _human_collab_hint(text: str) -> str:
    for part in text.splitlines():
        line_st = part.strip()
        if line_st.startswith("Завдання:") or line_st.startswith("Завдання сесії:"):
            return line_st.split(":", 1)[1].strip()[:120]
        if "voice assistant" in line_st.lower():
            return line_st[:120]
    return text.strip()[:120] or "collab task"


def _is_governor_human_collab(text: str) -> bool:
    return (
        "Engineering Agent Governor" in text
        or ("verdict" in text and "next_executor_prompt" in text)
        or "Collab сесія (Governor)" in text
    )


def _is_human_round_followup(text: str) -> bool:
    return "Раунд " in text and (
        "Переглянь зміни" in text
        or "Напиши повний промпт" in text
    )


def _is_human_seed(text: str) -> bool:
    if "Раунд " in text:
        return False
    return (
        "Collab сесія (Governor)" in text
        or "voice assistant" in text.lower()
        or "Human starter" in text
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
        responded = False
        if "CHATBANG_COLLAB_OK" in msg.upper() or (
            "CHATBANG_COLLAB_OK" in text.upper() and "ACKNOWLEDGE" in text.upper()
        ):
            sys.stdout.write("CHATBANG_COLLAB_OK\n")
            buffer.clear()
            responded = True
        elif "GOVERNOR_MODE_OK" in msg.upper() or (
            "GOVERNOR_MODE" in text.upper() and "ACKNOWLEDGE" in text.upper()
        ):
            sys.stdout.write("GOVERNOR_MODE_OK\n")
            buffer.clear()
            responded = True
        elif "CHATBANG_OK" in msg.upper() and "GOVERNOR_MODE" not in text:
            sys.stdout.write("CHATBANG_OK\n")
            buffer.clear()
            responded = True
        elif "CHATBANG_COLLAB_V1" in text:
            task = "collab task"
            for part in text.splitlines():
                line_st = part.strip()
                if line_st.startswith("Task:"):
                    task = line_st.split("Task:", 1)[1].strip()[:120]
                    break
                if line_st.startswith("Session task label:"):
                    task = line_st.split("Session task label:", 1)[1].strip()[:120]
                    break
            if "BOOTSTRAP" in text.upper():
                task = f"bootstrap: {task}"
            sys.stdout.write(_collab_json(task, source_text=text))
            buffer.clear()
            responded = True
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
            responded = True
        elif _is_governor_human_collab(text) and len(text) > 40:
            # Governor human-only sends one line per turn (seed, round, format retry).
            if len(buffer) == 1 and bool(msg):
                sys.stdout.write(_collab_json(_human_collab_hint(text), source_text=text))
                buffer.clear()
                responded = True
            elif not msg and len(buffer) > 1:
                sys.stdout.write(_collab_json(_human_collab_hint(text), source_text=text))
                buffer.clear()
                responded = True
            else:
                continue
        elif not msg and buffer:
            continue
        elif (
            msg
            and "Chatbang Governor" not in text
            and "CHATBANG_COLLAB_V1" not in msg
            and "CHATBANG_COLLAB_V1" not in text
            and len(buffer) == 1
        ):
            sys.stdout.write(f"ADVISOR: acknowledged ({len(msg)} chars in prompt)\n")
            buffer.clear()
            responded = True
        if responded:
            sys.stdout.write("> ")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
