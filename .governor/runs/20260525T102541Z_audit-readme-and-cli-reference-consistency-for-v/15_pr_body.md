## Summary

Audit README and CLI reference consistency for v1.0 final

- **Run ID:** `20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v`
- **Policy:** `docs`
- **Gate profile:** `fast`
- **Outcome:** PASS

## Validation

- Gate overall: **WARN**
- Profile compliance: **WARN**
- Validator verdict: **PASS**
- Policy compliance: **PASS**
- Evidence: `/home/shevchenkool/project/Engineering-agent-governor/.governor/runs/20260525T102541Z_audit-readme-and-cli-reference-consistency-for-v/14_evidence_bundle.json`

## Risk

- Governor does not merge, push, or deploy.
- No automatic repair dispatch loop.
- Runner profiles are local-only (.governor/config.json).

## Rollback / next action

- Revert commit if validation fails post-merge.
- Re-run gates after fixes: `python -m governor gate --run-id <id>`.

## Artifacts

- Review package: `15_review_package.md`, `15_review_package.json`
- Final report: `09_final_report.md`
