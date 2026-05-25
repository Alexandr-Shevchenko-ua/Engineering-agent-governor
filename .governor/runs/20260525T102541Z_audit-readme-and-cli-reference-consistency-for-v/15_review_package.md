# Review package

**Run ID:** `20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v`
**Task:** Audit README and CLI reference consistency for v1.0 final
**Policy:** `docs`
**Gate profile:** `fast`
**State / outcome:** FINAL_REPORT_READY / PASS
**Exported:** 2026-05-25T10:28:44Z

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

- Files: 0 (+0/-0)
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

See `/home/shevchenkool/project/Engineering-agent-governor/.governor/runs/20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v/14_evidence_bundle.json`

## Commands executed

- `python -m governor init --task 'Audit README and CLI reference consistency for v1.0 final' --policy docs --repo-path /home/shevchenkool/project/Engineering-agent-governor`
- `python -m governor plan create --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v --policy docs --gate-profile fast`
- `# Recommended after closure: python -m governor evidence export --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v`
- `python -m governor dispatch --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v --role executor --profile echo-test --approve --repo-path .`
- `python -m governor gate --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v`
- `python -m governor dispatch --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v --role validator --profile fake-validator --command python scripts/fake_agent.py --approve --repo-path .`
- `python -m governor report --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v`
- `python -m governor plan execute --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v --approve`
- `python -m governor evidence export --run-id 20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v`
