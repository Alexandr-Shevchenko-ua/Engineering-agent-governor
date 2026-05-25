# Release notes — v1.0.0-rc1

**PEP 440 version:** `1.0.0rc1`  
**Marketing label:** v1.0.0-rc1

## What Governor is

Engineering Agent Governor is a **local, delegation-first control plane** for engineering work done by external agents (for example Cursor Agent). It creates auditable run folders, prompts, gates, plans, evidence, and review packages — without calling external LLM APIs or running agents automatically.

## Safety model (not autopilot)

- **No background daemon** — every action is an explicit CLI invocation.
- **No automatic repair dispatch** — repair prompts are prepared; humans dispatch when ready.
- **No merge, push, or deploy** — Governor never changes remotes or production.
- **Dispatch requires `--approve`** — preview is the default for `dispatch` and plan execution.
- **`.governor/` is local and gitignored** — runner argv and run artifacts stay off the shared tree.
- **`governor.project.json` is tracked and secret-free** — gate profiles use built-in check names only (no arbitrary shell).

## Main workflows

1. **Manual step-by-step** — `init` → human pastes prompts → `record` → `gate` → `report`
2. **Bounded plan** — `plan create` → `plan execute --approve` (or `resume`)
3. **Governed run** — `run start --approve` with optional `--with-evidence` / `--with-review-package`
4. **Release validation** — `governor check --repo-path .` and `scripts/self_dogfood_release_check.py`

## Features by version (summary)

| Version | Highlights |
|---------|------------|
| v0.1–v0.2 | Runs, gates, dispatch preview/approve, state machine |
| v0.3 | Runner profiles (`.governor/config.json`) |
| v0.4–v0.5 | Repair packs, run plans |
| v0.6 | Plan resume, human checkpoints, evidence bundles |
| v0.7 | Policy packs |
| v0.8 | Governed `run start` / `resume`, preflight |
| v0.9 | `governor.project.json`, gate profiles, review packages |
| **v1.0.0-rc1** | CLI reference, `version` / `check`, CI, packaging polish, self-dogfood script |

## Upgrade notes from v0.9

- Version string is now `1.0.0rc1` (`python -m governor version`).
- New commands: `governor version`, `governor check` (optional `--smoke`).
- No breaking changes to run folder layout or `governor.project.json` schema v1.
- Use `governor check --repo-path .` before tagging releases on this repository.

## Known limitations

- No built-in Cursor/Claude CLI integration (use `--runner command` or profiles with your argv).
- Gates depend on local tools (`pytest`, `ruff`, …) when referenced in profiles.
- Policy packs may insert **human checkpoints** after `gate` — plan stops until `plan checkpoint --approve`.
- **No LICENSE file in repo yet** — add an explicit license before public distribution if required (TODO for maintainers).

## Validation commands

```bash
python -m governor version
python -m governor version --json
python -m governor project validate --repo-path .
python -m governor check --repo-path .
python -m governor check --repo-path . --smoke
pytest tests/ -v
python scripts/self_dogfood_release_check.py
git check-ignore .governor/config.json
git ls-files .governor   # should be empty
```

See also [docs/CLI_REFERENCE.md](CLI_REFERENCE.md), [docs/SELF_DOGFOODING.md](SELF_DOGFOODING.md), [docs/RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
