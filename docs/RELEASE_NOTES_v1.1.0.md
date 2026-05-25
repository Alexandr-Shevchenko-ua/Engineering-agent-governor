# Release notes — v1.1.0

**PEP 440 version:** `1.1.0`  
**Marketing label:** v1.1.0  
**Previous stable:** [v1.0.0](RELEASE_NOTES_v1.0.0.md) (`1.0.0`, tag `v1.0.0`)

## Highlights

- **Cursor Headless executor pack** — documented `agent -p` profiles (`cursor-headless-local`, ask-mode variant); local dogfood validated full write dispatch and read-only ask dispatch.
- **Chatbang Governor Advisor** — `governor advisor ask`, `plan advise`, `review advise` via optional `pexpect` bridge; artifacts `16_advisor_request_N.md` / `16_advisor_response_N.md` without mutating `run_state.json`.
- **CLI fixes** — `--chatbang-command` and `--advisor-provider` no longer clash with argparse `command` / `provider` dests.
- **Multiline echo stripping** — advisor captures strip full echoed prompts, not only the last line.

## New commands

| Command | Purpose |
|---------|---------|
| `governor advisor ask` | One-shot semantic advice (chatbang or configured provider) |
| `governor plan advise` | Plan-scoped advisor prompt from run folder |
| `governor review advise` | Review-package-scoped advisor prompt |

## Dependencies

- `pexpect>=4.8` on non-Windows platforms (core dependency for advisor bridge).
- Optional `[advisor]` / `[dev]` extras unchanged in intent; install with `pip install -e ".[dev]"` for tests.

## Docs and examples

- `docs/CURSOR_HEADLESS_RUNNER.md` — stdin `agent -p`, preview/approve dispatch, dogfood note.
- `docs/CHATBANG_GOVERNOR_ADVISOR.md` — advisor workflow and safety boundaries.
- `examples/governor.config.example.json` — `cursor-headless-local`, disabled `chatbang-local` template.

## Upgrade from v1.0.0

- Version: `python -m governor version` → `1.1.0`.
- No breaking changes to run folder layout or `governor.project.json` schema v1.
- Add local `.governor/config.json` (gitignored) with `agent` on PATH for headless profiles; see `docs/CURSOR_HEADLESS_RUNNER.md`.
- Advisor is **orthogonal** to executor dispatch: use `cursor-headless-local` for code changes, `governor advisor ask` for judgment.

## Known limitations

- Advisor bridge requires interactive terminal behavior; not supported on Windows without WSL.
- Headless executor uses `--output-format text` (not stream-json); use separate streaming script for live progress.
- LICENSE file still a maintainer decision (unchanged from v1.0.0).

## Validation (maintainer)

- `pytest`: 220+ passed (v1.1 tree).
- `governor check --repo-path .`: PASS.
- Smokes: `scripts/smoke_chatbang_advisor_workflow.py`, `cursor_runner_local_check.py`, echo governed run.
- Dogfood runs under `.governor/runs/` (local, not committed).
