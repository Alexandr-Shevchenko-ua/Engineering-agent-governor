# Review package

**Run ID:** `20260525T144111Z_v11-echo-governed-dogfood`
**Task:** v1.1 echo governed dogfood
**Policy:** `default`
**Gate profile:** `fast`
**State / outcome:** FINAL_REPORT_READY / PASS
**Exported:** 2026-05-25T14:41:52Z

## Project config

- Project: Engineering Agent Governor
- Default policy: `agentic-tooling`
- Default gate profile: `fast`

## Plan summary

- Status: PASS
- Steps: {'PASS': 4}
- Gate profile: `fast`

## Gate summary

- Overall: **WARN**
- Profile: `fast` (WARN)

## Validator

**Verdict:** PASS


## Diff budget

- Files: 11 (+194/-18)
- diff_budget check: PASS

## Sensitive paths

- None flagged

## Reviewer checklist

- [ ] Confirm task scope matches diff and final report.
- [ ] Review gate overall and required profile checks.
- [ ] Confirm validator verdict before merge.
- [ ] Gate WARN — acknowledge warnings explicitly.

## Risks / limitations

- Governor does not merge, push, or deploy.
- No automatic repair dispatch loop.
- Runner profiles are local-only (.governor/config.json).

## Evidence

See `/home/shevchenkool/project/Engineering-agent-governor/.governor/runs/20260525T144111Z_v11-echo-governed-dogfood/14_evidence_bundle.json`

## Commands executed

- `python -m governor init --task 'v1.1 echo governed dogfood' --policy default --repo-path /home/shevchenkool/project/Engineering-agent-governor`
- `python -m governor plan create --run-id 20260525T144111Z_v11-echo-governed-dogfood --policy default --gate-profile fast`
- `# Recommended after closure: python -m governor evidence export --run-id 20260525T144111Z_v11-echo-governed-dogfood`
- `python -m governor dispatch --run-id 20260525T144111Z_v11-echo-governed-dogfood --role executor --profile echo-test --approve --repo-path .`
- `python -m governor gate --run-id 20260525T144111Z_v11-echo-governed-dogfood`
- `python -m governor dispatch --run-id 20260525T144111Z_v11-echo-governed-dogfood --role validator --profile fake-validator --command python scripts/fake_agent.py --approve --repo-path .`
- `python -m governor report --run-id 20260525T144111Z_v11-echo-governed-dogfood`
- `python -m governor plan execute --run-id 20260525T144111Z_v11-echo-governed-dogfood --approve`
- `python -m governor evidence export --run-id 20260525T144111Z_v11-echo-governed-dogfood`
