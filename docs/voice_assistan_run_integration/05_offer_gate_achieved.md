# Offer gate achieved (google_senior_ai)

**Status:** Product simulation release gate **PASS** with independent judge **`offer`**.

## Verify locally

```bash
cd <voice_assistant_root>
bash scripts/verify_linux.sh
bash scripts/check_offer_gate.sh
```

Expected:

- `verification_gate: PASS`
- `independent_judge.offer: offer`
- `independent_judge.consistency` ≥ 6.5

## Shadow live (no mic)

Before enabling real microphone integration:

```bash
bash scripts/shadow_live_prompt.sh "Tell me about your production ML experience."
```

Checks ownership clause in the **live adapter** path (same `finalize_live_max_aggressive_answer` as replay).

## Governor collab

```bash
pkill -f chatbang; pkill -f 'chrome.*chatbang' || true
cd Engineering-agent-governor
bash docs/voice_assistan_run_integration/run_voice_assistant_collab.sh
```

Honest overall PASS: Chatbang `verdict: PASS` + `check_offer_gate.sh` + `eval_collab_session.py`.

## Intentionally not done

- `live_integration_allowed` remains **false** until human approves hardware soak.
