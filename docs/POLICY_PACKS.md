# Policy packs (v0.7.0)

**Policy packs** tailor intake artifacts, plan defaults, checkpoints, and evidence expectations to the kind of work you are doing. They are **not autopilot** — they only shape templates and defaults; every dispatch still needs `--approve`.

## Built-in policies

| Name | Use when |
|------|----------|
| `default` | General engineering task |
| `bugfix` | Defect fix with regression test evidence |
| `refactor` | Structure change, no behavior change |
| `docs` | Documentation-only updates |
| `test-only` | Tests without product code changes |
| `release` | Version, changelog, smoke validation |
| `agentic-tooling` | Governor/agent harness safety |

## Commands (no `.governor` required)

```bash
python -m governor policy list
python -m governor policy show --policy bugfix
python -m governor policy show --policy bugfix --json
python -m governor policy validate --policy bugfix
```

## Init with a policy

```bash
python -m governor init --task "Fix run-id validation" --policy bugfix --repo-path .
python -m governor init --task "Improve README" --policy docs --repo-path .
```

- Customizes `00`–`04` intake/prompt artifacts
- Stores `policy` in `run_state.json`
- `status` and `09_final_report.md` show the policy

## Plan create

```bash
python -m governor plan create --run-id <id> --executor-profile echo-test --validator-profile fake-validator --repo-path .
# Optional override:
python -m governor plan create --run-id <id> --policy release --repo-path .
```

If `--policy` is omitted, the run’s stored policy is used. Policy can set:

- Human checkpoints (e.g. after `gate` for bugfix)
- `auto_repair_prepare_on_fail` default
- Recommended `evidence export` (hint in commands only — **not** auto-run)

CLI flags still override (e.g. `--auto-repair-prepare-on-fail`, `--checkpoint-after`).

## Evidence bundle

`evidence export` includes:

- `policy`, `policy_expectations`
- `policy_compliance` — simple PASS/WARN/FAIL heuristic (missing artifacts, gate fail, policy-specific checks)

See [EVIDENCE_BUNDLES.md](EVIDENCE_BUNDLES.md).

## Policy fields (reference)

Each pack defines:

- `required_artifacts` — expected files for closure
- `recommended_gates` — gate names (informational)
- `default_checkpoints` / `plan_defaults.checkpoints`
- `risk_prompts`, `stop_conditions`
- `evidence_expectations`
- `max_repair_prompts`
- `plan_defaults` — auto repair, max steps, evidence recommendation

Definitions live in `governor/policy.py` (built-in, versioned with releases).

## Related

- [RUN_PLANS.md](RUN_PLANS.md) — checkpoints and resume
- [DOGFOODING.md](DOGFOODING.md) — end-to-end example
