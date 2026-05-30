# Chatbang ↔ Cursor Collab Mode (experimental)

**Status:** Experimental v1.8 — human-only JSON contract, Chatbang-fail stop, commit excludes `.governor/`.

## What it does

`governor collab start` automates the manual bridge you used between **chatbang** (review + next prompt) and **Cursor** (implementation):

```text
OPTIONAL round_00 (bootstrap):
  human seed file/text  →  chatbang first  →  Cursor executor

FOR each round 1..N (max N):
  chatbang review  →  verdict + next_executor_prompt
  Cursor executor  →  dispatch via profile (e.g. cursor-headless-local)
  gates            →  optional deterministic checks
  git commit       →  optional, policy-gated (--approve-commit or --autopilot)

OPTIONAL after loop (--audit-after):
  Cursor auditor on Engineering-agent-governor repo
  →  session/audit/*.md (governor improvement backlog)
```

Artifacts: `.governor/collab/<session-id>/round_XX/` and `audit/` when enabled.

## What it does not do

- No automatic `git push` (use `--approve-push` explicitly)
- No infinite loops (`--max-rounds`, default 3)
- No chatbang GitHub plugin integration (chatbang sees **local git snapshot** in prompt)
- Not a replacement for domain-specific verification (`manifest_check`, shadow-run policy, etc.)

## Requirements

- Linux/WSL + `pexpect` for chatbang
- `.governor/config.json` with enabled **executor** profile
- Git repo at `--repo-path` (recommended for commit policy)
- **`--approve`** or **`--autopilot`** required to run rounds (`--autopilot` also enables commit when policy allows)

## Quick start (smoke)

```bash
python -m governor project init --repo-path .
python -m governor config init --repo-path .
# enable echo-test or cursor-headless-local in .governor/config.json

python scripts/smoke_collab_workflow.py
```

## Real voice assistant repo

Point at the implementation tree (not the governor repo):

```bash
export VA_REPO=/path/to/agents-insiders-test-codex/runs/.../implementation/voice_assistant

python -m governor project init --repo-path "$VA_REPO"
python -m governor config init --repo-path "$VA_REPO"

python -m governor collab start \
  --task "Live contract reliability: audit flush, reports, packaging" \
  --max-rounds 5 \
  --executor-profile cursor-headless-local \
  --commit-policy if_gates_pass \
  --approve \
  --approve-commit \
  --repo-path "$VA_REPO"
```

### Voice assistant run (seed + autopilot + audit)

From the governor repo (close other chatbang windows first):

```bash
export VA_REPO=/path/to/.../implementation/voice_assistant
bash docs/voice_assistan_run_integration/run_voice_assistant_collab.sh
```

Or explicitly:

```bash
python -m governor collab start \
  --task "Voice assistant quality — Maximum Aggressive Offer Mode" \
  --chatbang-seed-file docs/voice_assistan_run_integration/starter_massage_for_chatbang.txt \
  --chatbang-human-only \
  --max-rounds 5 \
  --executor-profile cursor-headless-local \
  --autopilot \
  --audit-after \
  --auditor-profile cursor-headless-local \
  --commit-policy if_gates_pass \
  --continue-on-gate-warn \
  --chatbang-timeout 600 \
  --repo-path "$VA_REPO"
```

| Flag | Meaning |
|------|---------|
| `--chatbang-seed-file` | Human message to chatbang **before** round 1 (round `00`) |
| `--chatbang-human-only` | **No** `CHATBANG_OK` probe, `CHATBANG_COLLAB_OK` prime, or `CHATBANG_COLLAB_V1` wire — only seed file text + natural follow-ups in Chatbang UI |
| `--chatbang-prompt-pattern` | pexpect end-of-turn pattern (default `> `; change if your chatbang UI differs) |
| `--skip-preflight` | Skip chatbang probe (use if preflight hangs on your chatbang build) |
| `--autopilot` | No `--approve` / `--approve-commit` prompts |
| `--audit-after` | After N rounds, Cursor audits collab + governor repo → `audit/` |
| `--governor-repo-path` | Override governor checkout for audit executor |
| `--continue-on-chatbang-fail` | After timeout/error, still run Cursor if valid CONTINUE JSON was parsed (default: **stop**) |
| `--no-commit-exclude-dot-governor` | Include `.governor/` in auto-commits (default: **exclude** collab run artifacts) |

### Human-only mode (`--chatbang-human-only`)

Governor appends a **mandatory JSON contract** (Ukrainian) to every seed and follow-up message. Chatbang must reply with a fenced `json` block (`verdict`, `summary`, `next_executor_prompt`, `stop_reason`). Without JSON, Governor sets **HOLD** and does **not** invent a CONTINUE prompt (no legacy freeform fallback).

On missing JSON, Governor sends one **format retry** to Chatbang. Cursor receives a short **executor preamble** (no background `pytest`, prefer `scripts/verify_linux.sh`, do not edit `.governor/`).

`session.json` records `cli_options` and `chatbang_failures` for post-mortems.

## Chatbang response contract (`CHATBANG_COLLAB_V1`)

First fenced `json` block:

```json
{
  "verdict": "CONTINUE",
  "summary": "What you observed",
  "next_executor_prompt": "# Executor\n\n...",
  "stop_reason": null
}
```

| Verdict | Meaning |
|---------|---------|
| `CONTINUE` | Run executor with `next_executor_prompt` |
| `PASS` | Done — stop loop successfully |
| `HOLD` | Stop — human must intervene |
| `FAIL` | Stop — failed |

## Commit policies

| Policy | Behavior |
|--------|----------|
| `never` | No git commits |
| `if_dirty` | Commit when worktree dirty (needs `--approve-commit` or `--approve`) |
| `if_gates_pass` | Commit only when gates are not FAIL (WARN needs `--continue-on-gate-warn`) |

Commits use `git add` + `git commit` after `git diff --check` passes. By default, paths under `.governor/` are **not** staged (product code only).

## Commands

```bash
python -m governor collab start --task "..." --approve --repo-path .
python -m governor collab list --repo-path .
python -m governor collab show --session <id> --repo-path .
```

### Useful flags

| Flag | Purpose |
|------|---------|
| `--max-rounds` | Cap ping-pong (default 3) |
| `--executor-profile` | Cursor headless or echo-test |
| `--commit-policy` | When to commit |
| `--approve-commit` | Allow commits (with policy) |
| `--approve-push` | Push after commit (explicit) |
| `--skip-gates` | Skip gate step (not recommended) |
| `--accept-failed-executor` | Continue after non-zero executor exit |
| `--force-continue-on-hold` | If HOLD but prompt present, treat as CONTINUE |
| `--dry-run` | Create session folder only |

## vs other Governor modes

| Mode | Multi-round | Executor | Commit |
|------|-------------|----------|--------|
| `governor propose` | No | No | No |
| `advisor ask` | No | No | No |
| `collab start` | Yes | Yes | Optional |
| `run resume` | Plan steps | Yes | No |

## Related

- [CHATBANG_GOVERNOR_MODE.md](CHATBANG_GOVERNOR_MODE.md)
- [CURSOR_HEADLESS_RUNNER.md](CURSOR_HEADLESS_RUNNER.md)
- [voice_assistan_run_integration/01_chatbang_cursor_bridge_gap_analysis.md](voice_assistan_run_integration/01_chatbang_cursor_bridge_gap_analysis.md)
