# Final report

**Outcome:** PASS
**Run ID:** `20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v`
**Task:** Audit README and CLI reference consistency for v1.0 final
**Policy:** `docs` — Documentation-only changes; accuracy and examples over code gates.
**State:** FINAL_REPORT_READY
**Repo:** `/home/shevchenkool/project/Engineering-agent-governor`

## Scope

# Scope and assumptions

**Task:** Audit README and CLI reference consistency for v1.0 final  
**Policy:** `docs`

## In scope

- (what will change — aligned with docs policy)

- Assume code behavior is frozen; only docs change.

## Out of scope

- (what will not change)

## Facts

- (verified truths)

## Assumptions

... (6 more lines)

## Git / diff summary

Overall: **WARN**
Diff: 0 files, +0/-0 lines

## Executor output summary

# Dispatch output

**Dispatch status:** OK
**Runner:** echo
**Role:** executor
**Exit code:** 0
**Duration seconds:** 0.00
**Prompt:** 03_executor_prompt.md

## Stdout

# Echo dispatch (executor)

... (31 more lines)

## Validator output summary

# Dispatch output

**Dispatch status:** OK
**Runner:** command
**Role:** validator
**Exit code:** 0
**Duration seconds:** 0.01
**Prompt:** 04_validator_prompt.md

## Stdout

## Validator (fake_agent)

... (11 more lines)

**Validator verdict:** PASS

## Repair history

- Repair prompts: 0 (`none`)
- Repair outputs: 0 (`none`)
- repair_count: 0
- repair_prompt_count: 0

## Run plan

- Overall plan status: **RUNNING**
- Step counts: PASS=3, RUNNING=1
- Executor profile: echo-test
- Validator profile: fake-validator
- Reached report step: no

## Gate results

Overall: **WARN**
Diff: 0 files, +0/-0 lines

## Open risks

# Risk register

**Policy:** `docs`

| ID | Risk | Likelihood | Impact | Mitigation | Owner |
|----|------|------------|--------|------------|-------|
| R1 | Stale commands or wrong paths in docs | medium | medium | Mitigate per policy | owner |
| R2 | Examples that do not run | medium | medium | Mitigate per policy | owner |

## Stop conditions (policy)

- Undocumented code behavior changes
- Examples contradict current CLI/API

## Notes

- Update after gate and validator review.

## Human decision needed

No — unless gate-only or risks require review.

## Recommended next action

Review validator verdict; run gate again if needed, or: governor report --run-id <id>

## Commands executed (governor)

- `python -m governor init --task 'Audit README and CLI reference consistency for v1.0 final' --policy docs --repo-path /home/shevchenkool/project/Engineering-agent-governor`
- `python -m governor plan create --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v --policy docs --gate-profile fast`
- `# Recommended after closure: python -m governor evidence export --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v`
- `python -m governor dispatch --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v --role executor --profile echo-test --approve --repo-path .`
- `python -m governor gate --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v`
- `python -m governor dispatch --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v --role validator --profile fake-validator --command python scripts/fake_agent.py --approve --repo-path .`
- `python -m governor report --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v`

## Artifact list

- `00_task_intake.md`
- `01_scope_and_assumptions.md`
- `02_risk_register.md`
- `03_executor_prompt.md`
- `04_validator_prompt.md`
- `05_executor_output.md`
- `06_validator_output.md`
- `08_gate_results.json`
- `08_gate_results.md`
- `12_run_plan.json`
- `12_run_plan.md`
- `run_state.json`
- `trace.jsonl`
