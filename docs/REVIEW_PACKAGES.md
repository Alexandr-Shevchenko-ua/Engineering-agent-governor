# Review packages

Review packages are **MR/PR handoff artifacts** exported after a governed run reaches final report.

## Artifacts

| File | Purpose |
|------|---------|
| `15_review_package.md` | Human-readable review summary |
| `15_review_package.json` | Machine-readable bundle |
| `15_pr_body.md` | Concise PR/MR body (Summary, Validation, Risk, Rollback, Artifacts) |

## Export

```bash
python -m governor review export --run-id <id> --repo-path .
python -m governor review export --run-id <id> --format markdown|json|both
python -m governor review export --run-id <id> --include-trace   # optional trace in JSON
```

## Governed run integration

```bash
python -m governor run start --task "..." --approve --with-review-package ...
python -m governor run resume --run-id <id> --approve --with-review-package ...
```

Export runs only when state is `FINAL_REPORT_READY` (same rule as evidence).

`run status` and JSON summaries report `review_package_exists` and `pr_body_exists`.

## Settings

`review_package` in `governor.project.json` controls what the bundle emphasizes (evidence link, trace summary, commands, policy compliance). Export does not call external LLM APIs.
