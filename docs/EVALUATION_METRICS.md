# Run evaluation metrics (v1.4.0)

Governor v1.4 adds a **local metrics layer** to measure whether governed runs reduce manual chaos, rework, and reviewer burden — not whether an agent merely produced more output.

## What success means

| Success is | Success is not |
|------------|----------------|
| Lower manual interventions and repair loops | More lines changed |
| Shorter time-to-review with complete evidence | Hidden gate FAIL treated as PASS |
| MR accepted with little follow-up | `fake-validator` PASS mistaken for production quality |
| Repeatable runs within the same **task category** | Comparing agents on incomparable tasks |

Optimize for **less rework and less reviewer burden**, not agent verbosity or diff size.

## Artifacts

Per run (under `.governor/runs/<run_id>/`):

- `17_run_evaluation.json` — machine-readable metrics + scores
- `17_run_evaluation.md` — human summary

Global index (gitignored):

- `.governor/evaluations/evaluations.jsonl` — one JSON object per line, upserted by `run_id`

Exports (via CLI):

- `.governor/evaluations/evaluations.csv`
- `.governor/evaluations/evaluations.md`
- Optional dashboard: `governor evaluate summary --output .governor/evaluations/dashboard.md`

## Automatic vs manual metrics

**Automatic** (from `evaluate run`):

- Identity: run id, task, policy, state, outcome
- Flow: trace timestamps, dispatch durations, gate timing
- Friction: commands executed, repair loops, failed dispatch, force/replace flags
- Diff: gate `08_gate_results.json` (files/lines, budget, sensitive paths)
- Quality: gate overall, pytest summary, validator verdict from `06_validator_output.md`
- Evidence flags: final report, evidence bundle, review package, PR body

**Manual** (after MR / lead review — `evaluate annotate`):

- `manual_rework_minutes`
- `mr_outcome`: `accepted` | `needs_minor_changes` | `needs_major_rewrite` | `rejected` | `unknown`
- `post_run_defects_found`, `defect_types`
- `reviewer_comments_count`, `lead_followup_questions_count`
- `evidence_quality_score` (1–5), `reviewer_burden_score` (1–5, lower is better)

No LLM scoring — formulas are fixed and transparent in `governor/evaluation.py`.

## Commands

```bash
# Extract metrics for one run
python -m governor evaluate run --run-id <id> --repo-path .

# Show evaluation
python -m governor evaluate show --run-id <id> --repo-path .

# After MR review
python -m governor evaluate annotate --run-id <id> --repo-path . \
  --manual-rework-minutes 5 \
  --mr-outcome accepted \
  --reviewer-burden-score 2 \
  --evidence-quality-score 4

# Export index
python -m governor evaluate export --repo-path . --format csv
python -m governor evaluate export --repo-path . --format markdown

# Summary table
python -m governor evaluate summary --repo-path .
python -m governor evaluate summary --repo-path . --by policy
python -m governor evaluate summary --repo-path . --by executor_profile
```

## Scores (interpretation)

| Score | Direction | Meaning |
|-------|-----------|---------|
| `governor_friction_score` | Lower is better | Human interventions, repairs, failed dispatch, force/replace, rework minutes |
| `run_success_score` | Higher is better | Outcome, gates, validator, defects, evidence completeness |
| `reviewer_burden_reduction_signal` | Higher is better | Evidence/review artifacts present; fewer comments/follow-ups; manual burden scores |

These are **heuristics** for trend tracking across runs, not HR or billing truth.

## Workflow after merge

1. Run `evaluate run` when the governed run finishes (or re-run after `evidence export` / `review export`).
2. Open MR; after review, `evaluate annotate` with real rework and MR outcome.
3. Periodically `evaluate export` and `evaluate summary` to compare policies and executor profiles.

## Anti-patterns

- **Optimizing for lines changed** — large diffs often mean more review work.
- **Hiding failures** — do not annotate `accepted` when gates failed or defects were found post-merge.
- **Fake validator as quality** — `fake-validator` PASS only means the harness ran; use real validators for production signals.
- **Cross-category agent comparison** — compare `docs` runs to `docs`, `bugfix` to `bugfix`, with similar scope.

## Limitations (v1.4)

- No web dashboard or central server.
- Token/cost fields are optional placeholders unless you annotate them.
- `blocked_time_seconds` is approximated (total runtime minus summed dispatch durations).
- Proposal rejection counts are per-run ref only, not global proposal history.
