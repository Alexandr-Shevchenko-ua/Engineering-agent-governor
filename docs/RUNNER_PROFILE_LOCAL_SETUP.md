# Local runner profile setup (v1.0.0)

Governor passes the full role prompt (**`03_executor_prompt.md`**, etc.) on **stdin** to `runner: command` profiles. It does **not** ship Cursor, Claude, or Chatbang syntax in the codebase — you configure **`.governor/config.json`** locally (gitignored).

## Safety

| Rule | Why |
|------|-----|
| **Never commit** `.governor/config.json` | May contain machine-specific paths; runner argv is local |
| **No secrets in argv** | Use env-based auth for CLIs; Governor rejects obvious secret patterns |
| **Preview before `--approve`** | Dispatch does not run the process until you approve |
| **Not autopilot** | No background jobs, repair loops, merge/push/deploy from Governor |
| **Enable only after stdin test** | Prove `echo 'test' \| your-cli …` before `"enabled": true` |

Tracked project policy stays in **`governor.project.json`** (gate profiles, policies) — secret-free.

## 1. Inspect local CLIs

Run on your machine (missing tools are OK):

```bash
which cursor || true
cursor --help || true

which claude || true
claude --help || true

which chatbang || true
chatbang --help || true
```

**What we expect on a typical dev machine:**

| CLI | Role | Prompt via stdin? |
|-----|------|-------------------|
| `cursor` (remote-cli) | Editor (open files, extensions) | `-` reads **files into editor**, not agent prompts — **not suitable** as agent runner |
| `claude` (Claude Code) | Agent | **`claude -p`** reads prompt from **stdin** when non-interactive |
| `chatbang` | Browser-backed ChatGPT | No documented stdin agent contract — **keep disabled** until you verify |

Test stdin yourself (no Governor):

```bash
echo "Reply with exactly PONG." | claude -p --output-format text
```

Do not enable `claude-local` until this succeeds (auth/subscription configured).

## 2. Initialize local config

```bash
python -m governor config init --repo-path .
python -m governor config show --repo-path .
python -m governor config validate --repo-path .
```

Example template (tracked): `examples/governor.config.example.json`.

Draft profiles (disabled by default):

- `cursor-local` — empty `argv`, disabled
- `chatbang-local` — empty `argv`, disabled
- `claude-local` — suggested argv below, disabled until auth works

### Suggested `claude-local` argv (local only)

```json
"claude-local": {
  "runner": "command",
  "argv": ["claude", "-p", "--output-format", "text"],
  "timeout": 900,
  "enabled": false
}
```

Governor runs: `claude -p --output-format text` with prompt text on stdin, cwd = target repo.

**Do not** put API keys or tokens in `argv`.

## 3. Dispatch preview (no execution)

```bash
python -m governor init --task "Local runner smoke" --policy docs --repo-path .
RUN_ID=<id-from-output>

python -m governor dispatch --run-id "$RUN_ID" --role executor \
  --profile claude-local --allow-disabled-profile --repo-path .
```

Review the preview: argv, timeout, prompt excerpt, warnings. No subprocess runs without `--approve`.

For enabled smoke profiles:

```bash
python -m governor dispatch --run-id "$RUN_ID" --role executor \
  --profile echo-test --repo-path .
```

## 4. Execute with `--approve`

Only after preview looks correct and the CLI accepts stdin:

1. Set `"enabled": true` in `.governor/config.json` for that profile.
2. Re-run validate: `python -m governor config validate --repo-path .`
3. Execute:

```bash
python -m governor dispatch --run-id "$RUN_ID" --role executor \
  --profile claude-local --approve --repo-path .
```

On success, Governor writes `05_executor_output.md` and advances state. On failure, see `05_executor_output.failed.md` (state unchanged unless `--accept-failed-output`).

## 5. Governed run with local profiles

Smoke-safe defaults (echo + fake validator):

```bash
export PATH="$(pwd)/.venv/bin:$PATH"
python -m governor run start \
  --task "Runner profile validation" \
  --policy default \
  --use-default-profiles \
  --approve \
  --with-evidence \
  --with-review-package \
  --repo-path .
```

To use a **local** executor profile, omit `--use-default-profiles` and pass profiles in the plan or dispatch manually after `run start` stops for human/agent work.

For gate profile `fast`, keep `pytest` on `PATH` or use `--continue-on-gate-warn` when optional linters are skipped (see [SELF_DOGFOODING.md](SELF_DOGFOODING.md)).

## 6. Cursor / “agent” clarification

The `cursor` binary on many Linux/WSL setups is the **VS Code-compatible editor CLI**, not a documented “run agent with this prompt” API. Governor intentionally does **not** hardcode Cursor agent invocations.

If you use a separate Cursor Agent CLI or wrapper, add it yourself under a new profile name with argv you trust, after verifying stdin (or switch to manual paste + `governor record`).

## Related docs

- [CLI_REFERENCE.md](CLI_REFERENCE.md) — `config`, `dispatch`
- [SELF_DOGFOODING.md](SELF_DOGFOODING.md) — release checks on this repo
- `examples/governor.config.example.json` — starter profiles
