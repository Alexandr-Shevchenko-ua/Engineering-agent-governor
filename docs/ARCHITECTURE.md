# Engineering Agent Governor — architecture

**Version:** v1.3.x  
Governor is a **local control plane**, not an autonomous agent. Humans approve every execution step.

## Mental model

```text
                    ┌─────────────────────────────────────┐
                    │         Governor CLI (authority)     │
                    │  init · gate · plan · dispatch ·     │
                    │  run resume · check · safety audit   │
                    └──────────────┬──────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
         ▼                         ▼                         ▼
  Proposal providers          Execution runners          Deterministic gates
  (no repo writes)            (--approve only)           (pytest, git diff, …)
         │                         │
   chatbang / cursor-auto    Cursor Headless / echo / fake
```

## Roles

| Component | What it is |
|-----------|------------|
| **Governor CLI** | Authority layer: creates runs, validates proposals, runs gates, records artifacts, exports evidence. Does not “think” unless you invoke a provider. |
| **Cursor Headless Executor** | `runner: command` profile (e.g. `cursor-headless-local`) — **can modify the repo** when you `dispatch` or `run resume --approve`. |
| **Cursor Governor Provider** | `cursor-auto` + profile `cursor-governor-auto` — **read-only** proposals via `agent --mode ask` (model auto). Not an executor. |
| **Chatbang Governor Mode** | `governor propose --provider chatbang` — proposal JSON via pexpect; not an executor. |
| **Chatbang Advisor** | `advisor ask` on an **existing** run folder — guidance only; must not change `run_state.json`. |
| **Fake Validator** | `fake-validator` profile — CI/smoke validator only; not for production judgment. |

## Role comparison

| Role | Can modify repo? | Changes `run_state`? | Uses gates? | Recommended use |
|------|------------------|----------------------|-------------|-----------------|
| Governor CLI | No (orchestrates) | Yes (on approve/record) | Runs them | Always — source of truth |
| Cursor Headless Executor | Yes (when approved) | Via dispatch/resume | After executor | Implement bounded task |
| Cursor Governor Provider (`cursor-auto`) | **No** (ask mode) | No | No | New-task proposal |
| Chatbang Governor Mode | No | No | No | New-task proposal (terminal) |
| Chatbang Advisor | No | **No** (by contract) | No | Review stuck run / plan |
| Fake Validator | No | Via dispatch | N/A | Tests and smokes |

## Typical flows

### New task (proposal-first)

1. `governor governor propose` — chatbang or `cursor-auto`
2. `governor governor validate` / `show`
3. `governor governor apply --approve` — creates run + plan only
4. `governor run resume --approve` — executor + gates + validator

### Existing run (advice only)

1. `governor advisor ask --run-id <id>`
2. Human decides; use `dispatch` / `resume` separately

### Diagnostics

- `governor safety audit` — local config / gitignore / profile safety
- `governor diagnose --run-id <id>` — why stuck + next command
- `governor cleanup status` — `.governor` disk usage
- `governor evaluate run` — extract friction/success/reviewer metrics → `17_run_evaluation.*`

### Evaluation layer (v1.4)

```text
run artifacts (state, trace, gates, plan, evidence)
        │
        ▼
  governor/evaluation.py  ──► 17_run_evaluation.json|md
        │
        ▼
  .governor/evaluations/evaluations.jsonl  ──► export / summary
```

Post-MR: `evaluate annotate` supplies rework minutes, MR outcome, reviewer burden scores. Success = less chaos/rework/reviewer load, not more agent output.

## Local vs tracked

| Path | Git |
|------|-----|
| `governor.project.json` | Tracked (policies, gates) |
| `.governor/config.json` | **Ignored** (runner argv, secrets risk) |
| `.governor/runs/`, `proposals/`, `evaluations/` | **Ignored** (operational noise) |

## Related docs

- [CURSOR_GOVERNOR_PROVIDER.md](CURSOR_GOVERNOR_PROVIDER.md)
- [CHATBANG_GOVERNOR_MODE.md](CHATBANG_GOVERNOR_MODE.md)
- [CURSOR_HEADLESS_RUNNER.md](CURSOR_HEADLESS_RUNNER.md)
- [EVALUATION_METRICS.md](EVALUATION_METRICS.md)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
