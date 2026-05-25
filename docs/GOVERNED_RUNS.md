# Governed runs (v1.0)

**`governor run start`** compresses the safe delegation workflow into one explicit command. It is **not unsafe autopilot**: no background jobs, no infinite loops, no automatic repair dispatch, and dispatch still requires **`--approve`**.

## One command

```bash
python -m governor run start \
  --task "Fix run-id validation" \
  --policy bugfix \
  --executor-profile your-executor \
  --validator-profile your-validator \
  --with-evidence \
  --approve \
  --repo-path .
```

For local smoke / CI:

```bash
python -m governor run start \
  --task "Smoke test" \
  --policy default \
  --use-default-profiles \
  --approve \
  --with-evidence \
  --repo-path .
```

`--use-default-profiles` selects `echo-test` + `fake-validator` — **not** for production Cursor work.

## What `run start` does

| Phase | Without `--approve` | With `--approve` |
|--------|---------------------|------------------|
| Dry-run (`--dry-run`) | Prints intended steps; **creates nothing** | — |
| Preflight | — | Repo, git, `.governor` ignored, config if profiles |
| Init | Creates run + policy-tailored `00`–`04` | Same |
| Plan | Writes `12_run_plan.json` (policy checkpoints/defaults) | Same |
| Execute | **Skipped** — prints `run resume --approve` | Runs bounded plan |
| Evidence | Skipped unless final report | `--with-evidence` exports `14_evidence_bundle.*` |

## Exit codes

| Result | Code |
|--------|------|
| Plan **PASS** / `FINAL_REPORT_READY` | 0 |
| Stopped at **human checkpoint** (expected BLOCKED) | 0 |
| Plan **FAIL**, preflight FAIL, invalid policy/profiles | 1 |

## Checkpoints and resume

Bugfix/release/agentic-tooling policies may insert human checkpoints. When blocked:

```bash
python -m governor plan checkpoint --run-id <id> --step-id <step> --approve --note "Reviewed" --repo-path .
python -m governor run resume --run-id <id> --approve --with-evidence --repo-path .
```

## Shortcuts

```bash
python -m governor run status --run-id <id> --repo-path .
python -m governor run status --run-id <id> --json --repo-path .

python -m governor run resume --run-id <id> --approve --repo-path .
```

## Preflight

Before execution with `--approve`:

- Repository path exists
- Git worktree (WARN if missing)
- `.governor` gitignored (WARN if cannot verify)
- Valid `config.json` when using profiles

`--strict-preflight` — treat WARN as failure.

## Evidence

- `--with-evidence` exports only when state is **`FINAL_REPORT_READY`**
- Otherwise prints: *Evidence export skipped because final report is not ready.*
- No automatic export on FAIL/BLOCKED (unless you run `evidence export` manually later)

## Safety boundaries

| Allowed | Not allowed |
|---------|-------------|
| Explicit `--approve` dispatch | Background daemon |
| Policy-driven templates | Auto repair **dispatch** loops |
| Bounded `--max-steps` | Merge / push / deploy |
| Checkpoint human stop | Hardcoded Cursor CLI in core |
| Repair **prepare** on fail (policy) | External LLM APIs |

## Related

- [POLICY_PACKS.md](POLICY_PACKS.md)
- [RUN_PLANS.md](RUN_PLANS.md)
- [EVIDENCE_BUNDLES.md](EVIDENCE_BUNDLES.md)
- [DOGFOODING.md](DOGFOODING.md)
