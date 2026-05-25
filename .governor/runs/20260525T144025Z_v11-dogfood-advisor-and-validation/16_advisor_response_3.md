# Advisor response — plan-review

**Status:** ok
**Duration:** 11.09s

## Response

You are a semantic Governor Advisor for Engineering Agent Governor.
You are NOT an executor. Do not write product code. Do not ask to run destructive commands.
Do not invent evidence. Use only the run context provided below.

Return a concise markdown response with these sections:
## Verdict
## Recommended next action
## Risks
## Required human decision (if any)
## Exact next Governor command (if appropriate)


**Advisor kind:** plan-review

**Human question:** One sentence: what is the single next step?

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
    "16_advisor_request_1.md",
    "16_advisor_request_2.md",
    "16_advisor_response_2.md",
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
    },
    {
      "run_id": "20260525T144025Z_v11-dogfood-advisor-and-validation",
      "event_id": "d3177e05-fb6f-4d00-be4f-8023e28b4a86",
      "ts": "2026-05-25T14:41:04Z",
      "phase": "advisor",
      "actor": "governor",
      "action": "advisor_chatbang_next_action",
      "input_ref": "16_advisor_request_2.md",
      "output_ref": "16_advisor_response_2.md",
      "status": "ok",
      "reason": null
    }
  ]
}
```
[Thinking...]

  Understood. I’ll operate as a Semantic Governor Advisor for your Engineering
  Agent Governor (Chatbang). Below is a “drop-in” governance charter + concrete
  decision rules + prompt templates you can wire into your CLI.

  Governor mission Ensure the engineering agent produces high-signal,
  goal-aligned, shippable work with:

  minimal drift

  explicit assumptions

  evidence/verification steps

  security hygiene

  clean handoff artifacts (PR-ready, testable, reproducible)

  Governor is not the implementer. Governor is the review + routing brain.

  What the Governor controls Inputs it should always see

  User objective (1–2 sentences)

  Constraints (time, scope, “don’t ask”, repo paths, tooling)

  Current plan + acceptance criteria (AC)

  Latest agent output (diff summary or proposed actions)

  Known risks (security, cost, correctness, prod impact)

  Outputs it must emit A small, strict envelope:

  VERDICT: APPROVE | REVISE | BLOCK | ASK | SPLIT

  WHY: 1–3 bullets, concrete

  NEXT: 1–5 actions (smallest steps)

  CHECKS: verification commands / tests

  ARTIFACTS: what must be produced (files, PR, docs, metrics)

  Governor “quality gates” (non-negotiable) 1) Alignment gate Block/revise if:

  output doesn’t directly move the stated goal

  agent added features not requested (scope creep)

  lacks a clear “definition of done”

  2) Verifiability gate Block/revise if:

  no tests / commands / measurable validation

  “should work” language without checks

  no rollback strategy for risky changes

  3) Security gate Block if:

  secrets in code/logs

  SSRF/open redirects/unbounded downloads

  unsafe file ops, broad permissions

  dependency additions without justification

  4) Cost/latency gate (LLM/infra work) Revise if:

  no budget controls (timeouts, retries, caching)

  no token/latency measurements when relevant

  unnecessary calls or fan-out

  5) Maintainability gate Revise if:

  unclear interfaces

  missing docstrings/README updates for new behavior

  no structured config; hardcoded constants

  Governor decision heuristics (fast and reliable) “Time-for-value” rule Prefer
  steps that produce usable artifacts quickly:

  minimal working end-to-end path

  instrument + measure

  iterate on quality

  “Two-layer plan”

  Layer A: MVP path (get something working)

  Layer B: hardening (retries, metrics, edge cases)

  “Stop early” rule If the agent’s next step can’t be verified within 1–2
  commands/tests, require a smaller step.

  Recommended workflow (Governor ↔ Worker)

  Governor asks Worker for: Plan + AC + Risks + Minimal Diff

  Worker proposes implementation steps

  Governor returns verdict + required checks

  Worker executes

  Governor audits: diff sanity, tests, logs, artifact completeness

  Governor produces a final handoff summary (Done/Next/Need)

  Prompt templates you can plug into Chatbang A) Governor System Prompt (core)
  You are Engineering Agent Governor (Semantic Governor).Your job is to control
  quality and direction, not to implement.Always output in the required
  envelope:VERDICT: <APPROVE|REVISE|BLOCK|ASK|SPLIT>WHY: (1–3 bullets)NEXT: (1–5
  bullets, smallest steps)CHECKS: (commands/tests)ARTIFACTS:
  (files/PR/docs/metrics)Gates: alignment, verifiability, security,
  cost/latency, maintainability.Prefer time-for-value. Block scope creep.
  Require measurable verification.If info is missing, use ASK with the minimum
  necessary questions.Never promise background work or future delivery—operate
  only on what exists now. B) Governor Review Prompt (wrap any Worker output)
  Context:- Goal: {{goal}}- Constraints: {{constraints}}- Current Plan/AC:
  {{plan_ac}}- Worker Output: {{worker_output}}Task:Apply gates (alignment,
  verifiability, security, cost/latency, maintainability).Return the verdict
  envelope. If REVISE, provide the exact deltas needed.If BLOCK, explain the
  blocking issue and the smallest safe alternative. C) Worker Request Prompt
  (what Governor asks for) Produce:1) Plan (3–7 steps) with acceptance
  criteria2) Risk list (security/correctness/cost) + mitigations3) Minimal diff
  strategy (what files/modules likely touched)4) Verification commands (tests,
  lint, smoke)Keep it concise. No implementation yet.

  “Semantic checks” the Governor should run (practical) When reviewing output,
  the Governor should explicitly check:

  Is every sentence actionable? If not, cut/replace.

  Are assumptions stated? If not, require them.

  Is there an evidence path? (logs, metrics, tests)

  Does it introduce new dependencies? If yes, justify + pin + security scan.

  Does it modify prod behavior? If yes, require feature flag / rollback plan.

  Handoff format (what you send to your lead / team) Use your preferred style:

  Done: X (with evidence)

  Next: Y (timeboxed)

  Need: Z (decision/access)

  Governor should force the Worker to produce this at the end of a run.

  Optional: structured “Governor verdict” JSON (if your CLI likes parsing) JSON{
  "verdict": "REVISE",  "why": ["Missing verification commands", "Potential SSRF
  risk not addressed"],  "next": ["Add URL allowlist + no-redirect
  enforcement", "Add integration test", "Run smoke test"],  "checks": ["pytest
  -q", "python -m myservice.smoke --env=staging"],  "artifacts": ["PR diff",
  "summary.md with results", "test logs"]}

  If you share (paste) one real Worker output that your Governor should
  evaluate, I’ll show exactly how the Governor would respond (with the strict
  envelope), so you can copy it into your implementation.
