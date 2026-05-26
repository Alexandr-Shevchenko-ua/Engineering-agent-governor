# Dashboard Lite preparation (v1.5 input contract)

Local baseline for **v1.5 Dashboard Lite** — static report from `.governor/evaluations/evaluations.jsonl`. No web server.

## Prerequisites

- Governor **v1.4.1+** installed
- `.governor/` gitignored (fleet data stays local)
- All runs evaluated: `governor evaluate run --run-id <id>`
- **100% manual annotation** on fleet runs (post-MR fields)

## Refresh baseline (repeatable)

```bash
# Re-extract metrics for entire fleet
for d in .governor/runs/*/; do
  rid=$(basename "$d")
  python -m governor evaluate run --run-id "$rid" --repo-path . 2>/dev/null || true
done

# Summaries
python -m governor evaluate summary --repo-path .
python -m governor evaluate summary --repo-path . --by policy
python -m governor evaluate summary --repo-path . --by executor_profile
python -m governor evaluate summary --repo-path . --by governor_provider

# Exports (dashboard inputs)
python -m governor evaluate export --repo-path . --format csv
python -m governor evaluate export --repo-path . --format markdown
# Source of truth index:
#   .governor/evaluations/evaluations.jsonl
```

Verify annotation coverage:

```bash
python scripts/verify_evaluation_baseline.py --repo-path .
```

## Fleet cohorts (16 runs, annotated)

Use these labels in dashboard groupings — compare **within cohort**, not across unrelated tasks.

| Cohort | Runs | Dashboard use |
|--------|------|----------------|
| **Full closure + evidence** | `183224`, `144111`, `105525`, `102541` | Success / low reviewer burden exemplars |
| **Full closure, no exports** | `205711`, `075337` | Legacy manual path |
| **Near-full / stopped early** | `150343`, `102440` | `needs_minor_changes` |
| **Failure / negative** | `214854` | `rejected`, high friction |
| **Advisor-only** | `144025` | Advice without execution |
| **Smoke / abandoned** | `105551`, `145831`, `174112`, `174122`, `175731`, `175926` | `unknown` MR; do not treat as production success |

## Key fields for Dashboard Lite

| Field | Role |
|-------|------|
| `human_decision_count` | Preferred friction driver (not raw command count) |
| `active_execution_seconds` | Agent-active window |
| `human_gap_before_resume_seconds` | Human idle before resume |
| `gate_warn_count` | Includes profile-compliance WARN |
| `gate_subcheck_warn_count` | Per-check WARN only |
| `mr_outcome` | Manual post-merge truth |
| `manual_rework_minutes` | Human rework after run |
| `evidence_quality_score` | 1–5 manual |
| `reviewer_burden_score` | 1–5 manual (lower is better) |
| `governor_friction_score` / `run_success_score` / `reviewer_burden_reduction_signal` | Computed (transparent formulas) |

## Anti-patterns for dashboard readers

1. Do not rank runs by `diff_total_lines` or file count.
2. Do not treat `fake-validator` PASS as production quality (see per-run `17_run_evaluation.md`).
3. Do not average smokes with full closures without cohort filters.
4. `gate_overall` WARN may be profile compliance while sub-checks are PASS.

## Generate dashboard (v1.5+)

```bash
python -m governor evaluate dashboard --repo-path . --format both
# markdown only:
python -m governor evaluate dashboard --repo-path . --format markdown
# include smoke/unknown cohort in aggregates:
python -m governor evaluate dashboard --repo-path . --include-smokes
```

Defaults: `.governor/evaluations/dashboard.md` and `dashboard.html` (gitignored). See [EVALUATION_DASHBOARD.md](EVALUATION_DASHBOARD.md).

## Related docs

- [EVALUATION_METRICS.md](EVALUATION_METRICS.md)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — evaluation FAQ
