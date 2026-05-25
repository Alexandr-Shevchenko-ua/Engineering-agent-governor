# Repair workflow (v0.4)

Repair is a **controlled, human-approved** path from gate/validator findings to a new repair prompt and optional repair output. It is **not autopilot** and **not** an automatic repair loop.

## What repair does

| Step | Command | Creates / changes |
|------|---------|-------------------|
| Prepare | `repair prepare` | `11_repair_prompt_N.md` only |
| Execute | `dispatch --role repair --approve` or `record --role repair` | `07_repair_output_N.md` |
| Re-verify | `gate` (manual) | Updated `08_gate_results.*` |
| Close | `validator` / `report` (manual) | As usual |

Governor **never** auto-runs repair after validator, **never** auto-runs gate after repair, and **never** merges or deploys.

## Quick example

```bash
RUN_ID=<from governor list>

python -m governor dispatch --run-id "$RUN_ID" --role executor --profile echo-test --approve --repo-path .
python -m governor gate --run-id "$RUN_ID" --repo-path .

python -m governor repair prepare --run-id "$RUN_ID" --reason "Fix gate findings" --repo-path .

# Preview first
python -m governor dispatch --run-id "$RUN_ID" --role repair --profile echo-test --repo-path .
# Then approve
python -m governor dispatch --run-id "$RUN_ID" --role repair --profile echo-test --approve --repo-path .

python -m governor gate --run-id "$RUN_ID" --repo-path .
python -m governor dispatch --run-id "$RUN_ID" --role validator --profile fake-validator --approve --repo-path .
python -m governor report --run-id "$RUN_ID" --repo-path .
```

## Prepare rules

- Allowed states (default): `GATES_RUN`, `VALIDATOR_OUTPUT_RECORDED`, `REPAIR_RECORDED`
- Blocked without `--force`: `EXECUTOR_PROMPT_READY`, `INTAKE_CREATED`, `FINAL_REPORT_READY`, …
- Default **max 2** repair prompts per run (`--max-repairs`, `--force` to exceed)
- Does **not** change primary workflow state
- Appends `repair_prepare` to `trace.jsonl`

## Dispatch repair

- Requires existing `11_repair_prompt_N.md` (`repair prepare` first)
- `--repair-prompt N` selects prompt; default = latest
- Output: `07_repair_output_N.md`
- Non-zero exit → `07_repair_output_N.failed.md` (diagnostic only); state unchanged unless `--accept-failed-output`
- Success → `REPAIR_RECORDED`; **Next: run gate again**

## Record repair

`record --role repair` still works but **fails** if no repair prompt exists:

```
Prepare repair prompt first: python -m governor repair prepare --run-id <id>
```

## Bounded scope warning

Repair prompts instruct the agent to:

- Fix **only** listed gate/validator issues
- Avoid broad refactors and secrets
- State **HUMAN_DECISION_REQUIRED** when not safely fixable

## Outcomes

If you `report` while still in `REPAIR_RECORDED` after repair without re-gating, outcome may be:

`REPAIR_RECORDED_NO_POST_REPAIR_GATE`

Always re-run `gate` after repair before trusting closure.

Run plans can call `repair prepare` automatically on failure but **never** dispatch repair. **Plan resume** also does not dispatch repair — if gate failed and a repair prompt exists, resume is blocked until you repair manually. See [RUN_PLANS.md](RUN_PLANS.md).

## List artifacts

```bash
python -m governor repair list --run-id "$RUN_ID" --repo-path .
```
