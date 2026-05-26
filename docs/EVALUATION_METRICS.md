# Run evaluation metrics (v1.5.0)

Governor v1.4 adds a **local metrics layer** to measure whether governed runs reduce manual chaos, rework, and reviewer burden — not whether an agent merely produced more output.

**v1.4.1** improves metric accuracy (gate WARN accounting, human decision counting, flag parsing, active execution windows).

**v1.5.0** adds **Dashboard Lite** — static `dashboard.md` / `dashboard.html` from `evaluations.jsonl`. See [EVALUATION_DASHBOARD.md](EVALUATION_DASHBOARD.md).

Read `17_run_evaluation.md` per run for the structured summary.

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
- Dashboard (v1.5): `governor evaluate dashboard --repo-path . --format both`
  - `.governor/evaluations/dashboard.md`
  - `.governor/evaluations/dashboard.html`

## Automatic vs manual metrics

**Automatic** (from `evaluate run`):

- Identity: run id, task, policy, state, outcome
- Flow: calendar timing (`total_runtime_seconds`), active execution (`active_execution_seconds` from plan resume/execute windows), human gap before resume
- Friction: **`human_decision_count`** (preferred), `commands_executed_count` (raw), repair loops, flags from commands + trace
- Gate: `gate_overall`, `gate_overall_is_warn`, `profile_compliance_warn_count`, `gate_subcheck_warn_count`
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
| `governor_friction_score` | Lower is better | **`human_decision_count`**, repairs, failed dispatch, force-like/replace flags, **safety overrides (higher weight)**, rework minutes |
| `run_success_score` | Higher is better | Outcome, gates, validator, defects, evidence completeness |
| `reviewer_burden_reduction_signal` | Higher is better | Evidence/review artifacts present; fewer comments/follow-ups; manual burden scores |

These are **heuristics** for trend tracking across runs, not HR or billing truth.

## Workflow after merge

1. Run `evaluate run` when the governed run finishes (or re-run after `evidence export` / `review export`).
2. Open MR; after review, `evaluate annotate` with real rework and MR outcome.
3. Periodically `evaluate export` and `evaluate summary` to compare policies and executor profiles.

## Field guide (v1.4.1)

| Field | Meaning |
|-------|---------|
| `human_decision_count` | Approve/apply/resume/dispatch/record/repair/annotate-style steps — **preferred** for friction |
| `commands_executed_count` | Non-comment lines in `commands_executed` (raw log breadth) |
| `human_interventions_count` | Legacy alias of `human_decision_count` (not raw command count) |
| `gate_warn_count` | Sub-check WARNs **plus** profile-compliance WARN |
| `gate_subcheck_warn_count` | Only per-check `status: WARN` in `results[]` |
| `gate_overall_is_warn` | `overall == WARN` in `08_gate_results.json` |
| `active_execution_seconds` | Sum of plan execute/resume start→stop windows from trace |
| `blocked_time_seconds` | **Approximate** idle (calendar minus active execution when known) |
| `force_like_flags_count` | `--force`, `--force-unstructured` (commands + trace) |
| `safety_override_flags_count` | `--accept-failed-output`, `--allow-disabled-profile`, etc. |

Compare runs **within the same `task_category`** (e.g. docs vs docs). Do not rank agents on incomparable tasks.

### Gate WARN without sub-check WARN

`gate_overall` can be **WARN** when `profile_compliance` is WARN even if every named sub-check is PASS. Check `gate_profile_compliance_status` and `17_run_evaluation.md` § Gate summary.

### fake-validator

If `validator_profile` is `fake-validator`, PASS means the harness ran — not production validation. The markdown report includes an explicit caveat.

## Anti-patterns

- **Optimizing for lines changed** — large diffs often mean more review work.
- **Hiding failures** — do not annotate `accepted` when gates failed or defects were found post-merge.
- **Fake validator as quality** — `fake-validator` PASS only means the harness ran; use real validators for production signals.
- **Cross-category agent comparison** — compare `docs` runs to `docs`, `bugfix` to `bugfix`, with similar scope.

## Limitations (v1.4.1)

- No web dashboard or central server.
- Token/cost fields are optional placeholders unless you annotate them.
- `blocked_time_seconds` remains **approximate** (see `blocked_time_seconds_approximate`).
- Human decision heuristic may miss uncommon CLI phrasing or over-count bundled plan steps.
- Proposal rejection counts are per-run ref only, not global proposal history.
