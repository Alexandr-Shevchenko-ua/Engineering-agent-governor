# Chatbang Governor Mode (experimental)

**Version:** v1.2.0  
**Status:** Experimental — not autopilot.

## What it is

Chatbang Governor Mode lets **chatbang** act as a **semantic planner** that proposes a **bounded, auditable** Governor run. The proposal is stored locally under `.governor/proposals/`. A human reviews, validates, and explicitly applies it. **Cursor executes** only through normal Governor dispatch after apply.

**Architectural rule:** chatbang proposes → Governor validates → human approves → Cursor executes → gates decide → evidence records.

## What it is not

Chatbang Governor Mode does **not**:

- Execute Cursor or any executor
- Run shell commands
- Merge, push, or deploy
- Access secrets or production systems
- Bypass deterministic gates
- Change `run_state.json` during propose
- Auto-run plans on apply (v1.2)

## vs `governor advisor ask`

| | `advisor ask` | `governor propose` |
|---|----------------|-------------------|
| Scope | Existing run folder | New task → new proposal |
| Artifacts | `16_advisor_request_*.md` in run | `.governor/proposals/<id>/` |
| State | Must not change run state | No run until apply |
| Output | Guidance / review | Full bounded run proposal |

## Proposal lifecycle

1. **Propose** — `python -m governor governor propose --task "..." --repo-path .`
2. **Validate** — `python -m governor governor validate --proposal <id> --repo-path .`
3. **Review** — `python -m governor governor show --proposal <id> --repo-path .`
4. **Apply** (optional) — `python -m governor governor apply --proposal <id> --approve --repo-path .`
5. **Execute** (human) — `python -m governor run resume --run-id <id> --approve --repo-path .`

Statuses: `PROPOSED` → `APPLIED` | `REJECTED` | `EXPIRED`

## Safety boundaries

Validation **fails** on:

- `git push` / `git merge` / production deploy patterns
- Forbidden shell (`bash -c`, `sudo`, `rm -rf`, …)
- Secret-like tokens in proposal text
- Empty acceptance criteria, risks, or stop conditions
- Invalid policy name
- `UNSTRUCTURED_RESPONSE` without `--force-unstructured`

Apply refuses when validation fails (no bypass for safety failures except unstructured flag).

## Chatbang session tuning (v1.2+)

Governor **primes** each propose call before the full prompt:

1. One line: `GOVERNOR_MODE: … Acknowledge with exactly: GOVERNOR_MODE_OK`
2. Full propose prompt tagged `GOVERNOR_MODE_V12` with JSON example + repo metadata

This reduces advisor-style `VERDICT` / “paste context” replies. The saved prompt is in `governor_request.md` under each proposal folder.

If chatbang still returns unstructured output, use `governor validate` and either edit `proposal.md` or apply with `--force-unstructured` after human review.

**Observed chatbang behaviors (dogfood):**

| Response style | Governor handling |
|----------------|-------------------|
| Advisor VERDICT / “paste context” | `ADVISOR_MODE_LEAK` + unstructured |
| Echo of inline JSON example | `EXAMPLE_ECHO`; repair task from CLI |
| Custom `governor_mode` meta-schema stream | `CHATBANG_META_SCHEMA`; mapped to proposal fields |
| Proper fenced proposal JSON | `MEDIUM`/`HIGH` confidence; validate PASS |

Compact wire message + session prime reduced echo; full audit prompt is saved in `governor_request.md` only.

## Context budget

By default the chatbang prompt includes **metadata only**:

- `governor.project.json` summary (if present)
- Policy and gate profile names
- Runner profile **names** (not raw argv)
- Short `git status`

No file contents, no `.env`, no `.governor/config.json` argv values. All written artifacts are **redacted**.

Optional flags:

- `--include-repo-summary` — extra repo metadata
- `--experimental-allow-wide-context` — redacted argv display per profile

## Unstructured chatbang output

If chatbang does not return a parseable fenced `json` block:

- Proposal is saved with `confidence: LOW` and `UNSTRUCTURED_RESPONSE`
- Human must edit `proposal.md` / re-propose, or use `--force-unstructured` only after careful review
- Apply is blocked until validation passes

## Recommended workflow

```bash
python -m governor governor propose --task "Add feature X" --repo-path .
python -m governor governor validate --proposal <id> --repo-path .
python -m governor governor show --proposal <id> --repo-path .
python -m governor governor apply --proposal <id> --approve --repo-path .
python -m governor run resume --run-id <run-id> --approve --repo-path .
```

Use `--dry-run` on propose/apply to preview without calling chatbang or creating runs.

## Local storage

```
.governor/proposals/<proposal-id>/
  proposal.json
  proposal.md
  raw_chatbang_response.md
  trace.jsonl
```

`.governor/` is gitignored — proposals stay local.

## Requirements

- `pexpect` (non-Windows) for chatbang bridge
- Interactive `chatbang` or `python scripts/fake_chatbang.py` for CI
- `governor.project.json` recommended for policy/gate validation
