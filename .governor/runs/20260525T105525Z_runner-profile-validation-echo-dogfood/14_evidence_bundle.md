# Evidence bundle

**Run ID:** `20260525T105525Z_runner-profile-validation-echo-dogfood`
**Task:** Runner profile validation echo dogfood
**State:** FINAL_REPORT_READY
**Outcome:** PASS
**Policy:** `default`
**Exported:** 2026-05-25T10:55:50Z

## Policy compliance

- Overall: **PASS**

## Recommendation

Run completed with PASS; review evidence bundle before merge.

## Gate summary

- Overall: **WARN**
  - gate_profile: PASS
  - git_status_short: PASS
  - git_diff_check: PASS
  - pytest: PASS
  - diff_budget: PASS
  - sensitive_paths: PASS

## Validator

**Verdict:** PASS

# Dispatch output

**Dispatch status:** OK
**Runner:** command
**Role:** validator
**Exit code:** 0
**Duration seconds:** 0.01
**Prompt:** 04_validator_prompt.md

## Stdout

## Validator (fake_agent)

Verdict: PASS

## Stderr

_empty_

## Notes

- Output was captured by Governor dispatch.
- Redaction is heuristic; review before sharing.

## Run plan

- Plan status: PASS
- Step counts: {'PASS': 3, 'FAIL': 1}

## Repair history

- Prompts: []
- Outputs: []

## Commands executed

- `python -m governor init --task 'Runner profile validation echo dogfood' --policy default --repo-path /home/shevchenkool/project/Engineering-agent-governor`
- `python -m governor plan create --run-id 20260525T105525Z_runner-profile-validation-echo-dogfood --policy default --gate-profile fast`
- `# Recommended after closure: python -m governor evidence export --run-id 20260525T105525Z_runner-profile-validation-echo-dogfood`
- `python -m governor dispatch --run-id 20260525T105525Z_runner-profile-validation-echo-dogfood --role executor --profile echo-test --approve --repo-path .`
- `python -m governor gate --run-id 20260525T105525Z_runner-profile-validation-echo-dogfood`
- `python -m governor dispatch --run-id 20260525T105525Z_runner-profile-validation-echo-dogfood --role validator --profile fake-validator --command python scripts/fake_agent.py --approve --repo-path .`
- `python -m governor report --run-id 20260525T105525Z_runner-profile-validation-echo-dogfood`
- `python -m governor plan execute --run-id 20260525T105525Z_runner-profile-validation-echo-dogfood --approve`

## Artifacts

- `00_task_intake.md`
- `01_scope_and_assumptions.md`
- `02_risk_register.md`
- `03_executor_prompt.md`
- `04_validator_prompt.md`
- `05_executor_output.md`
- `06_validator_output.md`
- `08_gate_results.json`
- `08_gate_results.md`
- `09_final_report.md`
- `10_lead_update.md`
- `12_run_plan.json`
- `12_run_plan.md`
- `run_state.json`
- `trace.jsonl`

## Safety notes

- Governor does not merge, push, or deploy.
- Prompt bodies excluded unless --include-prompts.
- Repair dispatch is never automatic in plan workflows.

## Trace (recent)

- 2026-05-25T10:55:44Z gate (warn)
- 2026-05-25T10:55:44Z plan_step_finish (fail)
- 2026-05-25T10:55:44Z plan_execute_stop (fail)
- 2026-05-25T10:55:50Z plan_resume_start (ok)
- 2026-05-25T10:55:50Z plan_step_start (ok)
- 2026-05-25T10:55:50Z dispatch_validator (ok)
- 2026-05-25T10:55:50Z plan_step_finish (ok)
- 2026-05-25T10:55:50Z plan_step_start (ok)
- 2026-05-25T10:55:50Z plan_step_finish (ok)
- 2026-05-25T10:55:50Z plan_resume_stop (pass)
