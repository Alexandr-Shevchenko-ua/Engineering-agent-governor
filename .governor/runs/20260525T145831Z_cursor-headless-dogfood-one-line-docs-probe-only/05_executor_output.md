# Dispatch output

**Dispatch status:** OK
**Runner:** command
**Role:** executor
**Exit code:** 0
**Duration seconds:** 65.83
**Prompt:** 03_executor_prompt.md

## Stdout

**Ask mode is on** — I cannot edit files, run tests, or run `governor record` for you. Below is what the run expects, a concrete minimal plan, and a **ready-to-save** executor report you can paste into Agent mode or run yourself.

---

## What this run is

| Field | Value |
|--------|--------|
| **Run ID** | `20260525T145831Z_cursor-headless-dogfood-one-line-docs-probe-only` |
| **Policy** | `docs` — docs-only, no product code unless doc build requires it |
| **Goal** | Prove Cursor Headless executor → minimal doc diff → `record` → `gate` |
| **Scope** | Exactly **one line** changed in **one** doc file |

The prompt you pasted matches `executor_prompt_for_policy` for policy `docs` in `governor/policy.py` (mission, deliverables, `record` command).

---

## Short implementation plan

1. **Inspect** — `docs/CURSOR_HEADLESS_RUNNER.md` (read-only dogfood section), `docs/DOGFOODING.md`, `scripts/cursor_runner_local_check.py` (referenced commands).
2. **Edit** — Add **one** factual line under “read-only dogfood” in `docs/CURSOR_HEADLESS_RUNNER.md` (lines 43–47 today).
3. **Verify** — Optional: `python scripts/cursor_runner_local_check.py` (no file change required for `docs` policy).
4. **Skip** — pytest/product code unless you touched code (you should not).
5. **Record** — Save the deliverable block below as e.g. `executor-output.md`, then:

```bash
python -m governor record --run-id 20260525T145831Z_cursor-headless-dogfood-one-line-docs-probe-only --role executor --file executor-output.md --repo-path .
```

Switch to **Agent mode** if you want the agent to apply the edit and run checks.

---

## Suggested one-line change (minimal, accurate)

**File:** `docs/CURSOR_HEADLESS_RUNNER.md`  
**Place:** After the ask-mode `argv` example block (~line 47), before “Preview and execute”.

**Add:**

```markdown
**Docs probe:** use policy `docs` with a one-line doc fix, then `governor record` and `gate` — no product code required.
```

**Rationale:** Documents the intended Headless smoke path; aligns with `docs` policy and existing read-only dogfood section; does not invent CLI flags (verified against `governor/policy.py` and `DOGFOODING.md`).

**Alternative (if you prefer cross-link only):** one line in `docs/DOGFOODING.md` manual loop table pointing to `CURSOR_HEADLESS_RUNNER.md` for Headless executor — slightly broader than “probe only” but still valid.

---

## Executor deliverable (save as `executor-output.md`)

```markdown
# Executor output — 20260525T145831Z_cursor-headless-dogfood-one-line-docs-probe-only

## Implementation plan (short)

1. Read `docs/CURSOR_HEADLESS_RUNNER.md` read-only dogfood section and `docs` policy expectations.
2. Add one line documenting docs-policy Headless smoke (record + gate).
3. No product code changes; optional local cursor check script only.

## Changed files (one-line rationale each)

| File | Rationale |
|------|-----------|
| `docs/CURSOR_HEADLESS_RUNNER.md` | One-line **docs probe** note for policy `docs` + Headless smoke workflow. |

*(Fill after edit; if not applied yet, status: NOT APPLIED — Ask mode blocked implementation.)*

## Commands run (exit codes)

| Command | Exit | Notes |
|---------|------|--------|
| *(none in Ask mode)* | — | Implementer should run optional checks below. |

**Recommended when implementing:**

```bash
python scripts/cursor_runner_local_check.py    # expect 0 or WARN if agent not on PATH
git diff docs/CURSOR_HEADLESS_RUNNER.md
```

For `docs` policy, full `pytest` is optional unless you changed code.

## Test / lint / smoke results

- **Unit tests:** Not run (docs-only; no code change).
- **Lint:** Not run (single markdown line).
- **Smoke:** `cursor_runner_local_check.py` — *not run in Ask mode*; run locally to confirm `agent` on PATH matches doc claims.

## Doc files updated — accuracy notes

| Doc | Accuracy |
|-----|----------|
| `docs/CURSOR_HEADLESS_RUNNER.md` | New line references existing `docs` policy and manual `record`/`gate` flow in `docs/DOGFOODING.md`; does not add new argv flags. |
| Unchanged | `README.md` already links `CURSOR_HEADLESS_RUNNER.md`; `examples/governor.config.example.json` ask-mode argv matches doc block. |

## Risks and known gaps

- **Ask mode:** This report was produced without applying the diff or running commands.
- **Headless PATH:** `agent` / `cursor` availability is machine-specific; doc does not guarantee CI has Headless CLI.
- **Run folder:** `.governor/runs/20260525T145831Z_...` is gitignored; `record` must use run id **name only**, not a path (see `docs/DOGFOODING.md`).
- **Validator:** Still required after `gate` for full closure per state machine.

## Limitations

Executor work in Cursor Ask mode cannot modify the repo or invoke `governor record`. User should switch to Agent mode or apply the one-line edit manually, then run `record` with this file updated.
```

---

## Policy-aligned checks (for the real executor)

From `docs` policy acceptance criteria in `governor/policy.py`:

- Documentation matches current CLI (`record`, `gate`, policy name `docs`).
- Examples are illustrative or runnable — the probe line is procedural, not a new shell example.
- No product code unless doc build fails without it.

After `record`, continue the dogfood loop: `gate` → validator prompt → `record --role validator` → `report` (`docs/DOGFOODING.md`).

---

## Summary

You pasted the **Governor executor handoff** for a **minimal Headless dogfood** run. I mapped it to the repo’s `docs` policy and `CURSOR_HEADLESS_RUNNER.md` content. To **complete** the run: switch to **Agent mode** (or edit manually), apply the one-line doc change, run optional `cursor_runner_local_check.py`, update the table above with real exit codes, then:

`python -m governor record --run-id 20260525T145831Z_cursor-headless-dogfood-one-line-docs-probe-only --role executor --file executor-output.md`

I can apply the line and fill in real command results in Agent mode if you want that done end-to-end.

## Stderr

_empty_

## Notes

- Output was captured by Governor dispatch.
- Redaction is heuristic; review before sharing.
