# Evaluation Dashboard Lite (v1.5.0)

Static, local-only dashboard from `.governor/evaluations/evaluations.jsonl`. **No server, no web framework, no database, no telemetry.**

## Input

| Source | Role |
|--------|------|
| `.governor/evaluations/evaluations.jsonl` | **Only** dashboard input (one JSON object per run) |
| Per-run `17_run_evaluation.json` | Updated by `evaluate run`; index is upserted automatically |

If the index is missing or empty:

```text
No evaluations found. Run: python -m governor evaluate run --run-id <id>
```

The dashboard **does not** re-evaluate runs.

## Refresh evaluations

```bash
# Single run
python -m governor evaluate run --run-id <run-id> --repo-path .

# Fleet (example)
for d in .governor/runs/*/; do
  python -m governor evaluate run --run-id "$(basename "$d")" --repo-path .
done

python -m governor evaluate export --repo-path . --format csv
```

Optional baseline check:

```bash
python scripts/verify_evaluation_baseline.py --repo-path .
python scripts/verify_evaluation_baseline.py --repo-path . --min-runs 5 --require-annotations
```

## Annotate after MR review

Post-merge truth is manual:

```bash
python -m governor evaluate annotate --run-id <run-id> --repo-path . \
  --mr-outcome accepted \
  --manual-rework-minutes 10 \
  --evidence-quality-score 4 \
  --reviewer-burden-score 2 \
  --note "MR merged with one nit"
```

`mr_outcome`: `accepted`, `needs_minor_changes`, `needs_major_rewrite`, `rejected`, `unknown`.

Re-running `evaluate run` preserves manual fields when `17_run_evaluation.json` already exists.

## Generate dashboard

```bash
python -m governor evaluate dashboard --repo-path .
python -m governor evaluate dashboard --repo-path . --format markdown
python -m governor evaluate dashboard --repo-path . --format html
python -m governor evaluate dashboard --repo-path . --format both
```

Defaults (gitignored):

- `.governor/evaluations/dashboard.md`
- `.governor/evaluations/dashboard.html`

Options:

| Flag | Default | Meaning |
|------|---------|---------|
| `--include-smokes` | false | Include `smoke_or_unknown` cohort in dashboard view |
| `--include-unknown` | true | Include `mr_outcome=unknown` in view |
| `--min-runs` | 5 | Warn when view has fewer runs |
| `--top` | 5 | Worst/best/incomplete list size |
| `--json` | off | Print summary JSON to stdout |

Open `dashboard.html` in a browser locally (inline CSS only).

## Cohort labels (inferred)

| Cohort | Heuristic |
|--------|-----------|
| `full_with_evidence` | `final_report_exists` + `evidence_bundle_exists` + `review_package_exists` |
| `full_no_exports` | `outcome=PASS` + report, missing evidence or review |
| `incomplete_or_failed` | `outcome≠PASS` or `final_state≠FINAL_REPORT_READY` |
| `smoke_or_unknown` | `mr_outcome=unknown` and low evidence completeness |

Compare runs **within the same `task_category`**, not unrelated tasks.

## Dashboard sections

1. Executive summary (counts, MR outcomes, averages, caveats)
2. Cohort breakdown
3. Gate overall distribution
4. Friction vs success table (sorted worst → best)
5. By policy / executor / governor provider
6. Defect types
7. Reviewer burden / evidence counts
8. Runs to inspect (worst, best, incomplete, high rework)
9. Notes and caveats

## Anti-patterns

1. Do not rank by diff size or file count.
2. Do not treat `fake-validator` PASS as production validation quality.
3. Do not average smoke runs with full closures without `--include-smokes` awareness.
4. Do not treat heuristic scores as ground truth.
5. High `run_success_score` does **not** mean “more agent output is good” — success is less rework and reviewer burden.

## Related

- [EVALUATION_METRICS.md](EVALUATION_METRICS.md)
- [DASHBOARD_LITE_PREP.md](DASHBOARD_LITE_PREP.md)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
