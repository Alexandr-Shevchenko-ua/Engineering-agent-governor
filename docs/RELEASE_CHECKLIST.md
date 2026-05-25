# Release checklist

For **v1.0.0-rc1** also run `python -m governor check --repo-path .`, `python scripts/self_dogfood_release_check.py`, and see [RELEASE_NOTES_v1.0.0-rc1.md](RELEASE_NOTES_v1.0.0-rc1.md). (Governor)

Use before tagging a release. **Do not create tags automatically** from this doc alone.

## Version

- [ ] Bump `governor/__init__.py` `__version__`
- [ ] Bump `pyproject.toml` `version`
- [ ] README mentions correct version (e.g. v1.0.0-rc1)
- [ ] `python -m governor version` / `version --json`
- [ ] `python -m governor check --repo-path .` (and `--smoke` before tag)
- [ ] `python scripts/self_dogfood_release_check.py`
- [ ] `python -m governor project validate --repo-path .`
- [ ] `python scripts/smoke_project_governance_workflow.py`

## Tests and smoke

- [ ] `.venv/bin/pytest tests/ -v` — all pass
- [ ] `python -m governor --version` — expected version
- [ ] `python scripts/smoke_governor_workflow.py` — SMOKE OK
- [ ] `python scripts/smoke_dispatch_workflow.py` — DISPATCH SMOKE OK
- [ ] `python scripts/smoke_profile_workflow.py` — PROFILE SMOKE OK
- [ ] `python scripts/smoke_repair_workflow.py` — REPAIR SMOKE OK
- [ ] `python scripts/smoke_plan_workflow.py` — PLAN SMOKE OK
- [ ] `python scripts/smoke_resume_checkpoint_evidence_workflow.py` — V06 SMOKE OK
- [ ] `python scripts/smoke_policy_workflow.py` — POLICY SMOKE OK
- [ ] `python scripts/smoke_governed_run_workflow.py` — GOVERNED RUN SMOKE OK
- [ ] `python -m governor run start --help`
- [ ] `python -m governor policy list` / `policy show --policy bugfix`
- [ ] `repair prepare` / `dispatch --role repair` manual spot-check documented
- [ ] `python -m governor config validate --repo-path .` — OK (after `config init`)
- [ ] `git check-ignore -v .governor/config.json` — ignored
- [ ] Dispatch preview without `--approve` does not write executor/validator artifacts
- [ ] Invalid validator-before-executor dispatch does not create `06_validator_output.md`
- [ ] Non-zero dispatch writes `.failed.md` and leaves state unchanged (unless `--accept-failed-output`)
- [ ] `python -m governor doctor --repo-path .` — no FAIL on this repo
- [ ] `python -m governor list --repo-path . --limit 5` — readable output

## Security / gates

- [ ] Security regression: token in raw diff → WARN in gates, not leaked in `08_gate_results.json`
- [ ] Redaction warning still documented in README

## Docs

- [ ] README updated for new commands/behavior
- [ ] `docs/DOGFOODING.md`, `docs/RUNNER_PROFILES.md`, `docs/REPAIR_WORKFLOW.md`, `docs/RUN_PLANS.md`, `docs/EVIDENCE_BUNDLES.md`, `docs/POLICY_PACKS.md`, `docs/GOVERNED_RUNS.md` current
- [ ] This checklist reviewed

## Git

- [ ] `git status` clean (no tracked `.governor/`)
- [ ] `git ls-files .governor` returns nothing
- [ ] `git check-ignore -v .governor/index.json` confirms ignore (or only intentional untracked locals like `.governor/`)
- [ ] Commit message describes user-facing changes
- [ ] Push to remote

## Tag suggestion (manual)

Example after v0.1.2:

```bash
git tag -a v0.1.2 -m "v0.1.2: index, doctor, list, report ordering, dogfooding docs"
git push origin v0.1.2
```

Adjust message to match actual release notes.
