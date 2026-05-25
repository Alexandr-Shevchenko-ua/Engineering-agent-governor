# Governor provider innovation backlog (v1.3+)

Ideas grounded in v1.3 dogfood: **cursor-auto** produced HIGH-confidence structured proposals in ~36s; validation must tolerate safety language (“do not git push”) without false FAILs.

## Shipped from dogfood learnings

| Item | Why |
|------|-----|
| Negation-aware destructive checks | Proposals *forbid* push/merge in executor text — that is good, not FAIL |
| `scripts/provider_proposal_scorecard.py` | Objective A/B after `governor compare` — no extra LLM |
| README links to Governor Mode + Cursor provider docs | Discoverability for the two planner paths |

## Next high-leverage experiments

### 1. Provider tournament (local, manual)

Same task, both providers, scorecard pick winner:

```bash
python -m governor governor compare --task "..." --providers chatbang,cursor-auto --repo-path .
# … note proposal IDs from output …
python scripts/provider_proposal_scorecard.py --repo-path . \
  --proposal <chatbang-id> --proposal <cursor-id>
```

**Hypothesis:** Cursor wins on repo-native profile names; chatbang wins when session-primed for Governor JSON.

### 2. “Proposal lint” profile in config

A disabled profile `governor-proposal-linter` that runs a **fast** fake or echo check on `proposal.json` schema only — reuse validate logic without full propose cost.

### 3. Executor profile auto-suggest guardrail

When `recommended_profiles.executor` is write-capable but policy is `docs`, warn at validate time (WARN, not FAIL) — catches cursor-auto suggesting `cursor-headless-local` for docs.

### 4. Proposal → plan step mapping

Map `recommended_plan[].action` to `12_run_plan.json` step types automatically on apply (today: plan created from profiles, plan steps are generic). Reduces manual resume tuning.

### 5. Evidence bundle for proposals

Zip `proposal.md` + `governor_request.md` + validation decisions into `.governor/proposals/<id>/review_package/` for MR description paste — same pattern as run evidence export.

### 6. Headless stream-json observability (executor only)

Keep Governor provider on `--output-format text`; for **executor** runs optional `cursor-headless-stream-local` profile mirroring `stream-progress_cursor_cli_example.sh` with trace events in `trace.jsonl` — not for propose (keeps parsing simple).

## Anti-patterns (stay disciplined)

- Do not let `cursor-governor-auto` use write/agent mode “for speed”
- Do not auto-apply or auto-resume after propose
- Do not commit `.governor/config.json` or personal argv
- Do not merge provider and advisor code paths (different envelopes, different artifacts)

## Success metrics for v1.4

| Metric | Target |
|--------|--------|
| cursor-auto propose → validate PASS (docs tasks) | ≥ 90% without `--force-unstructured` |
| Time to first valid proposal | < 60s median locally |
| Apply → run + plan, zero execution | 100% in smoke |
| False destructive FAIL on negated text | 0 (regression test) |
