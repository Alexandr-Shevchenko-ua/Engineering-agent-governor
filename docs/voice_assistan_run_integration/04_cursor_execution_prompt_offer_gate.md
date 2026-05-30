# Cursor execution prompt — voice assistant offer gate

Copy-paste into Cursor Agent (product repo root). Use after Governor collab v1.8 or standalone.

---

## Context

Repo: `runs/20260502T142452Z_ai_voice_assistant_cli/implementation/voice_assistant`

Product: **Maximum Aggressive Offer Mode** — synthetic candidate reality for disclosed mock interviews. Release gate: `bash scripts/verify_linux.sh`.

**Do not:** run background `pytest`, edit `.governor/` unless required, mass-regenerate `offer_engine/reports/latest/**` without code changes.

## Objective

Reach **independent judge `offer_recommendation: offer`** for `google_senior_ai` while keeping:

- `verification_gate: PASS`
- `quality_gate: PASS`
- `live_integration_allowed: false` (do not enable live mic without explicit human approval)

## Must-read (5 min)

1. `offer_engine/reports/latest/verification_summary.json` — `quality_gate`, per-role judge
2. `offer_engine/reports/latest/google_senior_ai/independent_judge.json` — `missing_dimensions`, `blocking_turns`
3. `offer_engine/reports/latest/google_senior_ai/max_aggressive_replay.md` — weak turns (often turn 5 edge)
4. `offer_engine/hiring_committee_judge.py` — verdict thresholds
5. `offer_engine/world_model_query.py` — `finalize_live_max_aggressive_answer`

## Implementation hints (if judge still `another_round`)

| Blocker | Likely fix |
|---------|------------|
| `consistency` < 6.5 | High survivability + zero contradictions should cap bundle-risk penalty; verify red-team summary |
| Turn 5 `edge_perception` weak | Ensure edge answers include TensorRT/YOLO/FPS/latency + full senior scaffold after trim |
| `product_impact` | Answers must include `the business result was` with measurable outcome |

## Verify (mandatory)

```bash
cd <voice_assistant_root>
bash scripts/verify_linux.sh
```

Success when stdout ends with `PASS: release verification complete` and:

```bash
python3 -c "
import json
d=json.load(open('offer_engine/reports/latest/verification_summary.json'))
j=d['quality_gate']['roles']['google_senior_ai']
print('judge', j.get('judge_verdict'), 'near_offer', j.get('near_offer'), 'qg', d['quality_gate']['status'])
"
```

Target: `judge offer` (stretch) or `another_round` + `near_offer: true` (minimum for collab product gate).

## Commit message template

```
fix(offer-engine): raise google senior judge to offer gate (edge turn + consistency)

- Preserve ownership clause under live sentence cap
- Align hiring-committee scoring with senior scaffold and clean red-team runs
```

## Chatbang collab PASS (if using Governor)

Chatbang `verdict: PASS` only when **both**:

1. `verify_linux.sh` PASS
2. `google_senior_ai.judge_verdict` is `offer` OR (`another_round` AND `near_offer: true`)

See `starter_collab_pass_criteria.txt`.
