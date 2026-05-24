"""Markdown templates for intake artifacts and agent prompts."""

from __future__ import annotations

from governor.redaction import REDACTION_WARNING


def task_intake(task: str, repo_path: str, run_id: str) -> str:
    return f"""# Task intake

**Run ID:** `{run_id}`  
**Task:** {task}  
**Target repo:** `{repo_path}`

## Objective

{task}

## Acceptance criteria (fill in)

- [ ] Criteria 1
- [ ] Criteria 2

## Constraints

- Minimal scope; no broad refactors unless required
- No secrets in artifacts ({REDACTION_WARNING})
- Human delegates implementation to Cursor Agent; Governor records and gates only

## Out of scope

- (list explicitly)

## References

- (links, tickets, docs)
"""


def scope_and_assumptions(task: str) -> str:
    return f"""# Scope and assumptions

**Task:** {task}

## In scope

- (what will change)

## Out of scope

- (what will not change)

## Facts

- (verified truths)

## Assumptions

- (accepted defaults — label clearly)

## Open questions

- (blockers for lead)
"""


def risk_register() -> str:
    return """# Risk register

| ID | Risk | Likelihood | Impact | Mitigation | Owner |
|----|------|------------|--------|------------|-------|
| R1 | Scope creep | medium | high | Minimal diff policy | executor |
| R2 | Secret leakage in logs | low | critical | Redaction + no paste secrets | human |
| R3 | Unverified claims in agent output | medium | medium | Validator adversarial pass | validator |

## Notes

- Update after gate and validator review.
"""


def executor_prompt(task: str, repo_path: str, run_id: str) -> str:
    return f"""# Executor agent prompt

Paste this entire document into Cursor Agent (or equivalent). You are the **implementation executor**, not the Governor.

**Run ID:** `{run_id}`  
**Task:** {task}  
**Repo:** `{repo_path}`

---

## Mission

Implement the task with **minimal, focused changes**. The Engineering Agent Governor will record your output and run deterministic gates — it does not write product code for you.

## Required workflow

1. **Inspect first** — Read relevant files, tests, and conventions before editing.
2. **Plan briefly** — Write a short implementation plan (bullets) before making edits.
3. **Implement minimally** — Smallest correct diff; no drive-by refactors.
4. **Avoid** — Broad refactors, dependency upgrades unless necessary, touching `.env`/secrets/credentials unless explicitly requested.
5. **Run checks** — Execute available local checks (tests, lint) in the target repo.
6. **Report honestly** — Include limitations, risks, and what you did not verify.

## Deliverables (include all in your final message)

- Implementation plan (short)
- List of **changed files** with one-line rationale each
- **Commands run** with exit codes and summarized output
- Test/lint results (pass/fail/skipped)
- **Risks** and known gaps
- **Limitations** (what was not tested or not in scope)

## Scope discipline

- Keep scope minimal and aligned with: {task}
- Match existing code style and patterns
- Do not hide errors; surface blockers clearly

## Security

- Never commit or paste secrets, API keys, tokens, or private keys
- {REDACTION_WARNING}

## When done

Save your full response; the human will run:

`python -m governor record --run-id {run_id} --role executor --file <your_output.md>`
"""


def validator_prompt(task: str, repo_path: str, run_id: str) -> str:
    return f"""# Validator agent prompt

Paste this entire document into Cursor Agent. You are an **adversarial implementation auditor**, not the implementer.

**Run ID:** `{run_id}`  
**Task:** {task}  
**Repo:** `{repo_path}`

---

## Mission

Independently verify the executor's work against acceptance criteria. Assume claims may be wrong until inspected.

## Required checks

1. Read intake (`00_task_intake.md`) and scope (`01_scope_and_assumptions.md`).
2. Inspect **git diff** and changed files — look for hidden behavior changes.
3. Review executor output (`05_executor_output.md`) for unsupported claims.
4. Check gate results (`08_gate_results.json` / `.md`) if present.
5. Identify **missing evidence** (unrun tests, unverified edge cases).

## Verdict (return exactly one label on its own line)

Choose **exactly one**:

```
PASS
PASS_WITH_RISK
REPAIR_REQUIRED
HUMAN_DECISION_REQUIRED
```

## Output structure

- **Verdict:** (one of the four above)
- **Findings:** bullet list (severity-tagged)
- **Acceptance criteria:** met / partial / not met per item
- **Evidence reviewed:** files, commands, test outputs
- **Hidden risks:** behavior changes, security, data integrity
- **Repair instructions:** if REPAIR_REQUIRED, concrete steps

## Rules

- Do not re-implement unless necessary to prove a finding
- Be skeptical of "all tests pass" without evidence
- Escalate to HUMAN_DECISION_REQUIRED for ambiguous product/security tradeoffs

## When done

`python -m governor record --run-id {run_id} --role validator --file <your_output.md>`
"""
