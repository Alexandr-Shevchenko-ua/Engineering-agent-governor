# Advisor request — next-action

**Created:** 2026-05-25T14:40:47Z
**Question:** What should the human do next in this governed run?

---

You are a semantic Governor Advisor for Engineering Agent Governor.
You are NOT an executor. Do not write product code. Do not ask to run destructive commands.
Do not invent evidence. Use only the run context provided below.

Return a concise markdown response with these sections:
## Verdict
## Recommended next action
## Risks
## Required human decision (if any)
## Exact next Governor command (if appropriate)


**Advisor kind:** next-action

**Human question:** What should the human do next in this governed run?

## Run context (JSON)

```json
{
  "run_id": "20260525T144025Z_v11-dogfood-advisor-and-validation",
  "task": "v1.1 dogfood advisor and validation",
  "policy": "agentic-tooling",
  "state": "EXECUTOR_PROMPT_READY",
  "outcome": null,
  "repo_path": "/home/shevchenkool/project/Engineering-agent-governor",
  "repair_count": 0,
  "artifacts": [
    "00_task_intake.md",
    "01_scope_and_assumptions.md",
    "02_risk_register.md",
    "03_executor_prompt.md",
    "04_validator_prompt.md",
    "run_state.json",
    "trace.jsonl"
  ],
  "evidence": {
    "markdown": false,
    "json": false
  },
  "review_package": {
    "markdown": false,
    "json": false
  },
  "trace_last_events": [
    {
      "run_id": "20260525T144025Z_v11-dogfood-advisor-and-validation",
      "event_id": "cc5e0bb4-c29d-4a36-84dd-242f0fd706cf",
      "ts": "2026-05-25T14:40:25Z",
      "phase": "intake",
      "actor": "governor",
      "action": "init",
      "input_ref": null,
      "output_ref": "/home/shevchenkool/project/Engineering-agent-governor/.governor/runs/20260525T144025Z_v11-dogfood-advisor-and-validation",
      "status": "ok",
      "reason": "Created run for task: v1.1 dogfood advisor and validation (policy=agentic-tooling)"
    }
  ]
}
```
