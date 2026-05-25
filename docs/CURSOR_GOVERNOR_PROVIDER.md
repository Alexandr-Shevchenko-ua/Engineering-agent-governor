# Cursor Governor Provider (experimental)

**Version:** v1.3.0  
**Status:** Experimental — proposal-only; not autopilot.

## What this is

`cursor-auto` is a **Governor proposal provider**: it uses Cursor Headless CLI in **ask / read-only** mode with **model auto** to author bounded run proposals. It does **not** execute work, modify your repo, merge, push, or deploy.

This is **not** the same as **Cursor as Executor**:

| Role | Profile (typical) | Can modify repo? |
|------|-------------------|------------------|
| **Governor provider** | `cursor-governor-auto` | **No** — ask/read-only proposals only |
| **Executor** | `cursor-headless-local`, `cursor-headless-ask-local` | Yes — when you `run resume --approve` |

Governor still follows **proposal-first** lifecycle: propose → validate → apply (run + plan only) → human `run resume` with an **executor** profile.

## Requirements

- Local `.governor/config.json` (gitignored; never commit)
- Profile `cursor-governor-auto` with `runner: command` and **non-empty** `argv`
- argv must include read-only ask mode, e.g. `--mode ask`
- No secrets in argv; no hardcoded personal paths in the repository

Recommended argv (verify against **your** Cursor CLI — syntax may differ):

```json
["agent", "-p", "--force", "--mode", "ask", "--model", "auto", "--output-format", "text"]
```

If your CLI does not support `--model auto`, use the verified local flag (document only in your local config, not in git).

Default shipped template has `"argv": []` and `"enabled": false` so CI does not require Cursor.

## Local setup

```bash
python -m governor config init --repo-path .
python -m governor config validate --repo-path .
```

Edit `.governor/config.json` — enable `cursor-governor-auto` and fill `argv` (see above).

Optional checks:

```bash
python scripts/cursor_governor_provider_local_check.py --repo-path .
python scripts/cursor_governor_provider_local_check.py --repo-path . --probe
```

## Propose flow

```bash
python -m governor governor propose \
  --task "Small docs-only change: improve Cursor Governor Provider docs" \
  --provider cursor-auto \
  --policy docs \
  --cursor-profile cursor-governor-auto \
  --repo-path .

python -m governor governor validate --proposal <proposal-id> --repo-path .
python -m governor governor show --proposal <proposal-id> --repo-path .
python -m governor governor apply --proposal <proposal-id> --approve --no-execute --repo-path .
python -m governor run resume --run-id <run-id> --approve --continue-on-gate-warn --with-evidence --with-review-package --repo-path .
```

CLI options:

| Flag | Default | Notes |
|------|---------|--------|
| `--provider` | `chatbang` | Use `cursor-auto` for Cursor Governor |
| `--cursor-profile` | `cursor-governor-auto` | Must exist in local config |
| `--cursor-timeout` | `900` | Max `1800` |
| `--allow-disabled-profile` | off | Discouraged |
| `--allow-write-capable-governor-provider` | off | Discouraged; skips ask-mode argv check |

## Compare providers (optional)

```bash
python -m governor governor compare \
  --task "..." \
  --providers chatbang,cursor-auto \
  --policy docs \
  --repo-path .
```

Writes `.governor/proposals/<compare-id>/comparison.md` — does not apply.

## Safety

Proposal flags may include:

- `CURSOR_GOVERNOR_PROVIDER`, `READ_ONLY_PROVIDER`
- `PROVIDER_FAILED` — non-zero Cursor exit; **apply blocked**
- `WRITE_CAPABLE_PROVIDER_BLOCKED` — argv not ask/read-only
- `UNSTRUCTURED_RESPONSE` — parse failure

Validation fails if provider mode is write-capable or `PROVIDER_FAILED` is set.

## CI / tests

- `scripts/fake_cursor_governor.py` — fake provider (no real Cursor)
- `scripts/smoke_cursor_governor_provider_workflow.py`
- `tests/test_governor_providers.py`

## Compare and score (initiative tools)

After `governor compare` or two separate `propose` runs:

```bash
python scripts/provider_proposal_scorecard.py --repo-path . \
  --proposal <chatbang-proposal-id> --proposal <cursor-proposal-id>
```

Objective rubric (confidence, prompt size, plan steps, validate PASS, safety flags). See [GOVERNOR_PROVIDER_INNOVATION.md](GOVERNOR_PROVIDER_INNOVATION.md) for the roadmap.

## Limitations (v1.3)

- Model **auto** only for cursor-auto provider metadata
- No automatic execution from Governor
- No compare in mandatory CI unless you add it
- Real Cursor quality depends on local CLI version and argv
