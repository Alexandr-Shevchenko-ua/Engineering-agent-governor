# Engineering Agent Governor

Local **delegation-first control plane** for engineering work executed by external agents (e.g. Cursor Agent). **v0.1.2** adds run index, `list`/`doctor`, correct final-report ordering, and dogfooding docs.

## What this is

- Task intake and assumption/risk artifacts
- Ready-to-paste **executor** and **validator** prompts
- Recording of delegated agent outputs (audit-trail protected)
- Deterministic **git/tooling/security** gates (raw-diff security scan, redacted artifacts)
- Auditable `trace.jsonl` and human-readable reports

## What this is not

- Not a coding agent (does not implement product features)
- Not autopilot (no automatic agent dispatch)
- No external LLM API calls
- No Cursor CLI integration (v0.2+)
- No background daemons or production system access

## Quickstart

`--repo-path` works **before or after** the subcommand:

```bash
cd /path/to/target-repo

python -m governor init --task "Centralize retry policy" --repo-path .
python -m governor status --repo-path .
# or: python -m governor --repo-path . status

# Paste .governor/runs/<run-id>/03_executor_prompt.md into Cursor Agent
python -m governor record --run-id <run-id> --role executor --file /path/to/output.md --repo-path .

python -m governor gate --run-id <run-id> --repo-path .

# Paste 04_validator_prompt.md, then record validator output
python -m governor record --run-id <run-id> --role validator --file /path/to/validator.md --repo-path .

python -m governor report --run-id <run-id> --repo-path .
```

After `init`, state is **`EXECUTOR_PROMPT_READY`** — paste the executor prompt next.

Optional entry point after `pip install -e .`:

```bash
gov init --task "My task" --repo-path .
```

## Commands

| Command | Purpose |
|---------|---------|
| `init` | Create timestamped run under `.governor/runs/` (creates `.governor` only here) |
| `status` | Show latest or specific run (does not create `.governor`) |
| `list` | List runs from `.governor/index.json` (`--limit`, `--json`) |
| `doctor` | Readiness check (does not create `.governor`) |
| `record` | Store outputs; executor/validator protected unless `--replace` |
| `gate` | Run local checks → `08_gate_results.json` / `.md` |
| `report` | Generate `09_final_report.md` and `10_lead_update.md` |

**Dogfooding:** [docs/DOGFOODING.md](docs/DOGFOODING.md) — using Governor on this repo.

**Smoke test:** `python scripts/smoke_governor_workflow.py`

## Manual workflow with Cursor Agent

1. **init** — Intake, scope, risks, executor/validator prompts → `EXECUTOR_PROMPT_READY`
2. **Human** — Paste `03_executor_prompt.md` into Cursor Agent
3. **record --role executor** — Save agent response (`--file` or `--text`)
4. **gate** — Git + optional tools + security heuristics on **raw** diff (stored artifacts redacted)
5. **Human** — Paste `04_validator_prompt.md`; one verdict label required
6. **record --role validator** — Use `--replace` only if intentionally overwriting
7. **report** — Explicit outcome (verdict dominates; gate-only outcomes labeled clearly)

## State machine

`INTAKE_CREATED` (internal, during init) → **`EXECUTOR_PROMPT_READY`** → `EXECUTOR_OUTPUT_RECORDED` → `GATES_RUN` → `VALIDATOR_OUTPUT_RECORDED` → (`REPAIR_RECORDED`) → `FINAL_REPORT_READY` / `HUMAN_DECISION_REQUIRED`

## Audit trail protection

- First `record` for **executor** or **validator** creates `05_*` / `06_*`
- Repeat record without **`--replace`** exits with error (non-zero)
- **human_note** appends; **repair** uses numbered `07_repair_output_N.md`

## Safety and sensitive data

- **trace.jsonl**, recorded outputs, and gate details may contain sensitive data — redaction is heuristic only
- **Do not paste secrets** into recorded outputs
- Security gates scan the **raw** git diff; written gate files must not echo secrets
- Review artifacts before sharing outside the team

## Report outcomes (v0.1.1)

| Situation | Outcome |
|-----------|---------|
| Validator verdict present | `PASS`, `PASS_WITH_RISK`, `REPAIR_REQUIRED`, `HUMAN_DECISION_REQUIRED` |
| Gates only, PASS | `GATES_PASS_NO_VALIDATOR` |
| Gates only, WARN | `GATES_WARN_NO_VALIDATOR` |
| Gates only, FAIL | `GATES_FAILED` |
| Prompts only | `INTAKE_ONLY` |

Lead update **Need from lead** is explicit when gates WARN/FAIL or validator is missing.

## Known limitations

- No automatic agent invocation
- Redaction is heuristic only
- Gates run in the **target repo** from `run_state.json`
- Optional tools skipped when absent (never fail solely for missing pytest/ruff)
- Git detection uses `git rev-parse --is-inside-work-tree` (not `.git` directory presence)

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/pytest tests/ -v
```

## Release

See [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) before tagging.

## Planned v0.2

- Cursor CLI / Claude Code dispatcher hooks (bounded, human-approved)
- Per-repo gate profiles
