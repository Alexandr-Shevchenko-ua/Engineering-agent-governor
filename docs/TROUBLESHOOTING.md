# Troubleshooting

Common failures when using Engineering Agent Governor v1.3.x locally.

## Gates

### Gate WARN — ruff / mypy / optional tools missing

The **fast** gate profile may WARN when optional linters are not installed. Governor still records results; use `--continue-on-gate-warn` on `run resume` if you accept the WARN.

Install tools or switch `gate_profile` in `governor.project.json` to match your machine.

### pytest not on PATH

Fast profile runs `pytest -q`. Use the same Python/venv as Governor:

```bash
.venv/bin/python -m governor run resume --run-id <id> --approve --repo-path .
```

### Gate WARN on large working tree

Dogfood or feature branches with many unstaged files trigger **diff_budget** or **git_status** WARN. Narrow changes, stash unrelated work, or use `--continue-on-gate-warn` after review.

## Dispatch and resume

### Output artifact already exists

Re-dispatch without `--replace` fails when `05_executor_output.md` (or validator) exists.

```bash
python -m governor dispatch --run-id <id> --role executor --approve --replace --repo-path .
```

### Invalid run-id — must be folder name, not path

Use the id under `.governor/runs/`, e.g. `20260525T183224Z_my-task`, not a full path.

```bash
python -m governor diagnose --run-id 20260525T183224Z_my-task --repo-path .
```

### `run resume` does nothing without `--approve`

Preview is default. Add `--approve` to execute plan steps.

## Chatbang

### Echo / unstructured proposal

Chatbang may return advisor-style text or example JSON. Indicators: `UNSTRUCTURED_RESPONSE`, `EXAMPLE_ECHO`, `CHATBANG_META_SCHEMA`. Use `governor validate`; retry propose; see [CHATBANG_GOVERNOR_MODE.md](CHATBANG_GOVERNOR_MODE.md).

### Timeout

Increase `--timeout` on `governor propose` or `advisor ask`. Fake chatbang in CI avoids real terminal latency.

## Cursor

### Ask mode vs write mode

| Profile | Mode | Use |
|---------|------|-----|
| `cursor-governor-auto` | ask | **Proposals only** (`cursor-auto`) |
| `cursor-headless-ask-local` | ask | Read-only executor guidance |
| `cursor-headless-local` | write | **Edits repo** when dispatch approved |

Ask mode will **not** apply README/code edits — use a write executor profile for implementation.

### Profile disabled or empty argv

```bash
python -m governor config init --repo-path .
python -m governor config validate --repo-path .
python scripts/cursor_governor_provider_local_check.py --repo-path .
```

Fill `argv` locally; do not commit `.governor/config.json`.

## Proposals

### Validation FAIL on “git push” in executor text

Proposals often say “do not run git push”. v1.3.1+ uses negation-aware checks. Upgrade or re-validate after pull.

### `PROVIDER_FAILED` blocks apply

Cursor provider exited non-zero. Inspect `raw_chatbang_response.md` in the proposal folder; fix argv/auth; re-propose.

## Git / `.governor`

### `.governor` accidentally tracked

```bash
git rm -r --cached .governor
echo ".governor/" >> .gitignore
python -m governor safety audit --repo-path .
```

### Secrets in config argv

Governor refuses argv that look like tokens. Use environment auth; never commit `.governor/config.json`.

## Evaluation metrics (v1.4.1)

### `gate_warn_count` is 0 but gate overall is WARN

Check `gate_profile_compliance_status` in `08_gate_results.json`. Overall WARN often comes from **profile compliance** while every named sub-check is still PASS. Re-run:

```bash
python -m governor evaluate run --run-id <id> --repo-path .
```

Read `17_run_evaluation.md` § Gate summary.

### Friction score still looks high

`human_decision_count` (not `commands_executed_count`) drives friction. Status/show/diagnose/evaluate export are excluded. Re-evaluate after v1.4.1+.

### `blocked_time_seconds` is huge

Calendar span includes human idle time before `plan resume`. Prefer **`active_execution_seconds`** and **`human_gap_before_resume_seconds`** in `17_run_evaluation.md`.

### fake-validator PASS in evaluation

Harness success only. Use a real validator profile for production signals; the evaluation markdown includes a caveat when `validator_profile=fake-validator`.

See [EVALUATION_METRICS.md](EVALUATION_METRICS.md).

## Stuck run?

```bash
python -m governor diagnose --run-id <id> --repo-path .
```

## Disk usage

```bash
python -m governor cleanup status --repo-path .
python -m governor cleanup runs --repo-path . --keep-last 20 --dry-run
python -m governor cleanup runs --repo-path . --keep-last 20 --approve
```
