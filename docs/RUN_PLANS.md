# Run plans (v0.5)

A **run plan** is a local, explicit workflow artifact for a governor run. It is **not autopilot**: no background jobs, no dynamic agent creation, no infinite loops, and **no automatic repair dispatch**.

## Artifact

| File | Purpose |
|------|---------|
| `.governor/runs/<run-id>/12_run_plan.json` | Machine-readable plan + step statuses |
| `.governor/runs/<run-id>/12_run_plan.md` | Human-readable summary |

Plans are **gitignored** with `.governor/`.

## Default workflow

1. `dispatch_executor` (requires `--approve` on execute)
2. `gate`
3. `dispatch_validator`
4. `report`

Optional: `--auto-repair-prepare-on-fail` adds a conditional **repair prepare** path. On gate/validator failure, Governor runs `repair prepare` and **stops** — it does **not** dispatch repair.

## Commands

```bash
RUN_ID=<from governor list>

python -m governor plan create \
  --run-id "$RUN_ID" \
  --executor-profile echo-test \
  --validator-profile fake-validator \
  --repo-path .

python -m governor plan show --run-id "$RUN_ID" --repo-path .

# Preview (dry-run)
python -m governor plan execute --run-id "$RUN_ID" --dry-run --repo-path .

# Execute (dispatch steps need --approve)
python -m governor plan execute --run-id "$RUN_ID" --approve --repo-path .
```

### Create options

- `--executor-profile` / `--validator-profile` — preferred (validated via `config.json`)
- `--executor-runner` / `--validator-runner` + `--executor-command` / `--validator-command`
- `--auto-repair-prepare-on-fail`
- `--force` — overwrite existing plan
- `--dry-run` — print plan only

### Execute options

- `--approve` — **required** if plan includes dispatch steps
- `--until STEP_ID` — stop after completing that step
- `--dry-run` — list steps only
- `--continue-on-gate-warn` — do not stop on gate WARN
- `--replace` — forwarded to dispatch
- `--max-steps` — default 10 (hard cap)

## Safety boundaries

| Rule | Behavior |
|------|----------|
| Bounded steps | `--max-steps` default 10 |
| Approvals | Dispatch never runs without `--approve` |
| No repair dispatch | Only `repair_prepare` on failure; then stop |
| Preconditions | Steps check state/artifacts at execution time |
| Skip | Executor/validator output already present → SKIPPED (unless `--replace`) |
| Secrets | Secret-like argv rejected at plan create |
| Profiles | Disabled/invalid profiles fail at create |

## FAIL / WARN handling

- **Gate FAIL** → plan stops; optional `repair prepare` if enabled
- **Gate WARN** → plan stops by default; use `--continue-on-gate-warn` to proceed
- **Validator dispatch non-zero** → FAIL + optional repair prepare

## When to use humans

- Plan `BLOCKED` or `STOPPED` → inspect `12_run_plan.md` and `trace.jsonl`
- After auto repair prepare → human runs repair via `dispatch --role repair` or `record` manually, then `gate` again
- Outcome `REPAIR_RECORDED_NO_POST_REPAIR_GATE` if reporting without re-gating

## Related docs

- [RUNNER_PROFILES.md](RUNNER_PROFILES.md) — profile configuration
- [REPAIR_WORKFLOW.md](REPAIR_WORKFLOW.md) — manual repair (not auto-dispatched by plans)
- [DOGFOODING.md](DOGFOODING.md) — full manual loop
