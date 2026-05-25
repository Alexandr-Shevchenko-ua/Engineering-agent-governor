# Evidence bundles (v0.7.0)

An **evidence bundle** is the lead/MR-review artifact for a governor run: one markdown file for humans and one JSON file for tooling.

## Export

```bash
python -m governor evidence export --run-id <id> --repo-path .
python -m governor evidence export --run-id <id> --repo-path . --format markdown
python -m governor evidence export --run-id <id> --repo-path . --format json
```

Writes:

- `14_evidence_bundle.md` — narrative summary, gate/validator, plan, commands, recommendation
- `14_evidence_bundle.json` — same facts in machine-readable form

Trace event: `evidence_export`.

## What is included

- Run metadata (task, state, outcome, repair counts, **policy**)
- **Policy compliance** summary (PASS/WARN/FAIL heuristic vs policy expectations)
- Plan summary (if `12_run_plan.json` exists)
- Gate summary from `08_gate_results.json`
- Validator verdict and short output excerpt
- Repair history (prompt/output indices)
- Human checkpoints pointer (`13_human_checkpoints.md`)
- Commands executed and artifact list
- Recent trace events (not full history)
- Safety notes and **final recommendation** (merge/no-merge guidance)

## What is excluded by default

Full **prompt bodies** (`03_executor_prompt.md`, `04_validator_prompt.md`) are not embedded in the bundle unless you opt in:

```bash
python -m governor evidence export --run-id <id> --include-prompts --repo-path .
```

Default omission keeps bundles safe to paste into tickets and MRs without duplicating huge templates.

## Status and report

- `governor status` shows `Evidence: yes/no`
- `governor status --json` includes `evidence_bundle_exists`
- `09_final_report.md` mentions the bundle when `14_evidence_bundle.*` exists

## Typical workflow

1. Run a plan (or manual gate/validator path) to completion or a deliberate stop.
2. Approve any **human checkpoints** (`plan checkpoint --approve --note "..."`).
3. **Resume** if the plan stopped at a checkpoint: `plan resume --approve`.
4. **Export evidence** before opening an MR or sending a lead update.
5. Attach or link `14_evidence_bundle.md` in the MR description; use JSON for automation.

Evidence export is **not autopilot** — it does not dispatch agents, merge, push, or deploy.
