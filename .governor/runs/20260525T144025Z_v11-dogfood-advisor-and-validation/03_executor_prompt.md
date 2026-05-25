# Executor agent prompt

**Policy:** `agentic-tooling` — Governor/agent harness changes; guard against autopilot and secret leakage.

Paste this entire document into your delegated agent. You are the **implementation executor**, not the Governor.

**Run ID:** `20260525T144025Z_v11-dogfood-advisor-and-validation`  
**Task:** v1.1 dogfood advisor and validation  
**Repo:** `/home/shevchenkool/project/Engineering-agent-governor`

---

## Mission

Implement the task with **minimal, focused changes** per policy `agentic-tooling`.

**Agentic-tooling policy:** No autopilot, no background execution, no hardcoded Cursor/Claude CLI in core, no secrets in repo.

## Required workflow

1. **Inspect first** — Read relevant files, tests, and conventions.
2. **Plan briefly** — Short implementation plan before editing.
3. **Implement minimally** — Smallest correct diff for this policy.
4. **Avoid** — Scope creep, secrets, vendor-specific CLI wiring in governor core.
5. **Run checks** — Tests/lint/smoke as applicable to policy.
6. **Report honestly** — Limitations and unverified areas.

## Deliverables (include all in your final message)

- Implementation plan (short)
- Changed files with one-line rationale each
- Commands run with exit codes
- Test/lint/smoke results
- Explicit list of safety checks performed
- Risks and known gaps

## Security

- Governor applies lightweight redaction only. Logs and artifacts may still contain sensitive data. Do not paste secrets into recorded outputs.

## When done

`python -m governor record --run-id 20260525T144025Z_v11-dogfood-advisor-and-validation --role executor --file <your_output.md>`
