# Chatbang Governor Advisor (v1.1)

**chatbang is not an executor.** It is the **semantic Governor Advisor** layer: bounded advice from run context via interactive terminal prompt `> `, driven by Governor through **pexpect**.

| Layer | Tool | Role |
|-------|------|------|
| Deterministic | Governor CLI | State machine, gates, plans, evidence, review packages |
| Executor | Cursor Headless (local profile) | Code/docs implementation |
| Semantic advisor | chatbang + pexpect | Next action, risks, plan/evidence critique |

## How it works

1. Governor builds **compact run context** (no full prompt bodies by default).
2. Writes `16_advisor_request_N.md` under `.governor/runs/<run-id>/`.
3. Spawns `chatbang`, waits for `> `, sends advisor prompt, waits for next `> `, captures `child.before`.
4. Redacts output, writes `16_advisor_response_N.md`, appends trace (`phase: advisor`).
5. **Does not** change `run_state.json`, dispatch Cursor, or modify the git tree.

## Install

```bash
pip install 'engineering-agent-governor[advisor]'
# or: pip install 'pexpect>=4.8'
```

On Windows, pexpect is not supported; advisor chatbang is unavailable with a clear error.

## Usage

```bash
python -m governor advisor ask --run-id <id> --provider chatbang --kind next-action --repo-path .
python -m governor advisor ask --run-id <id> --provider chatbang --kind risk-review \
  --question "What should I do next?" --repo-path .
python -m governor advisor ask --run-id <id> --provider chatbang --kind evidence-review --dry-run --repo-path .

python -m governor plan advise --run-id <id> --provider chatbang --repo-path .
python -m governor review advise --run-id <id> --provider chatbang --repo-path .
```

### Kinds

| Kind | Purpose |
|------|---------|
| `next-action` | What should the human do next? |
| `risk-review` | Risks and stop conditions |
| `plan-review` | Critique run plan |
| `evidence-review` | Closure / evidence sufficiency |
| `repair-advice` | Repair strategy (no auto dispatch) |

### Options

- `--timeout` (default 180, max 900)
- `--max-output-chars` (default 20000)
- `--chatbang-command` — override executable (e.g. fake script for tests)
- `--dry-run` — write request only
- `--include-prompts` — include full executor/validator prompts in context (off by default)
- `--force` — allow ask when final report exists

## Good vs bad use cases

**Good:** next action, risk review, evidence review, repair advice, plan critique.  
**Bad:** direct repo code generation, secret handling, bypassing gates, background orchestration, replacing Cursor executor.

## Local check (optional, not CI)

```bash
python scripts/chatbang_advisor_local_check.py
python scripts/chatbang_advisor_local_check.py --use-fake
python scripts/chatbang_advisor_local_check.py --require
```

## CI-safe smoke

```bash
python scripts/smoke_chatbang_advisor_workflow.py
```

Uses `scripts/fake_chatbang.py`, not real chatbang.

## Example automation pattern (reference)

Your working pattern: `pexpect.spawn("chatbang")` → `expect("> ")` → `sendline(msg)` → read until next prompt. Governor's `governor/chatbang_bridge.py` implements this with timeout, redaction, and safe child teardown.

See `scripts/chatbang_run_example.py` for a minimal standalone sample (not used by Governor at runtime).

## vs Chatbang Governor Mode (v1.2)

| | `advisor ask` | `governor propose` |
|---|----------------|-------------------|
| When | Existing run | New task |
| Output | `16_advisor_*` in run folder | `.governor/proposals/<id>/` |
| Creates run | No | Only on `governor apply --approve` |

Governor Mode is **experimental** planning — see [CHATBANG_GOVERNOR_MODE.md](CHATBANG_GOVERNOR_MODE.md).
