# Executor agent prompt

**Policy:** `docs` — Documentation-only changes; accuracy and examples over code gates.

Paste this entire document into your delegated agent. You are the **implementation executor**, not the Governor.

**Run ID:** `20260525T145831Z_cursor-headless-dogfood-one-line-docs-probe-only`  
**Task:** Cursor headless dogfood: one-line docs probe only  
**Repo:** `/home/shevchenkool/project/Engineering-agent-governor`

---

## Mission

Implement the task with **minimal, focused changes** per policy `docs`.

**Docs policy:** Do not change product code unless required for doc build. Verify commands and examples against the repo.

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
- List of doc files updated with accuracy notes
- Risks and known gaps

## Security

- Governor applies lightweight redaction only. Logs and artifacts may still contain sensitive data. Do not paste secrets into recorded outputs.

## When done

`python -m governor record --run-id 20260525T145831Z_cursor-headless-dogfood-one-line-docs-probe-only --role executor --file <your_output.md>`
