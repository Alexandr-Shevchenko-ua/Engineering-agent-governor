# Cursor Headless executor (local profile)

**Role:** Cursor Headless CLI is the **executor** runner — it implements tasks in the target repo.  
**Not:** chatbang (semantic advisor) or Governor autopilot.

Governor does **not** ship Cursor argv syntax or personal paths. You verify Headless CLI on your machine, then fill **`cursor-headless-local`** in gitignored `.governor/config.json`.

## Safety

- Dispatch requires **`--approve`** (preview default).
- Prompt is sent on **stdin** to `runner: command` profiles.
- No merge, push, deploy, or background daemon from Governor.
- Keep secrets out of `argv` (use Cursor auth env / config).

## Verify locally

```bash
which cursor
cursor --help
python scripts/cursor_runner_local_check.py
```

On many installs the headless entrypoint is the **`agent`** CLI (also `cursor agent`), not the editor `cursor` binary.

Reference script (local): `scripts/stream-progress_cursor_cli_example.sh` uses:

```bash
agent -p --force --output-format stream-json --stream-partial-output "…"
```

Governor records **plain text** from stdout; use **`text`** output (prompt on **stdin**):

```json
"cursor-headless-local": {
  "runner": "command",
  "description": "Cursor Agent headless executor",
  "argv": ["agent", "-p", "--force", "--output-format", "text"],
  "timeout": 1800,
  "enabled": true
}
```

For **read-only dogfood** (no repo writes), use a separate profile with `--mode ask`:

```json
"argv": ["agent", "-p", "--force", "--mode", "ask", "--output-format", "text"]
```

Verified locally: `echo "prompt" | agent -p --force --output-format text` returns agent output.
- **Dogfood:** Cursor Agent dispatch via Governor profile `cursor-headless-local` validated (agent -p, stdin prompt).

## Preview and execute

```bash
python -m governor init --task "My task" --policy agentic-tooling --repo-path .
python -m governor dispatch --run-id <id> --role executor \
  --profile cursor-headless-local --allow-disabled-profile --repo-path .
python -m governor dispatch --run-id <id> --role executor \
  --profile cursor-headless-local --approve --repo-path .
```

## Governed run (manual profile selection)

Do **not** use `--use-default-profiles` (echo/fake). Pass executor profile explicitly when your plan supports it:

```bash
export PATH="$(pwd)/.venv/bin:$PATH"
python -m governor run start \
  --task "Feature X" \
  --policy agentic-tooling \
  --executor-profile cursor-headless-local \
  --validator-profile fake-validator \
  --approve \
  --continue-on-gate-warn \
  --repo-path .
```

Use **`fake-validator`** or a local validator profile until validator Headless is configured.

## Architecture

```text
Governor CLI (state, gates, evidence)
    → dispatch --approve → cursor-headless-local (executor)
    → advisor ask (optional) → chatbang (semantic advisor only)
```

See [RUNNER_PROFILE_LOCAL_SETUP.md](RUNNER_PROFILE_LOCAL_SETUP.md), [CHATBANG_GOVERNOR_ADVISOR.md](CHATBANG_GOVERNOR_ADVISOR.md).
