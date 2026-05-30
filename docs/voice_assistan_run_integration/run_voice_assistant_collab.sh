#!/usr/bin/env bash
# Voice assistant collab: seed → Chatbang → Cursor (autopilot) → optional governor audit.
set -euo pipefail

GOV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VA_REPO="${VA_REPO:-/home/shevchenkool/project/agents-insiders-test-codex/runs/20260502T142452Z_ai_voice_assistant_cli/implementation/voice_assistant}"
SEED_FILE="${SEED_FILE:-$GOV_ROOT/docs/voice_assistan_run_integration/starter_massage_for_chatbang.txt}"
PASS_CRITERIA="${PASS_CRITERIA:-$GOV_ROOT/docs/voice_assistan_run_integration/starter_collab_pass_criteria.txt}"
SEED_COMBINED="${SEED_COMBINED:-/tmp/voice_assistant_collab_seed_combined.txt}"

cd "$GOV_ROOT"

if [[ ! -f "$SEED_FILE" ]]; then
  echo "Seed file not found: $SEED_FILE" >&2
  exit 1
fi

python scripts/setup_voice_assistant_governor_config.py --repo-path "$VA_REPO"

echo "Prerequisite: close ALL chatbang terminals and Chatbang Chrome windows."
echo "If collab fails with profile lock, run: pkill -f chatbang; pkill -f 'chrome.*chatbang'"
echo "Governor spawns a NEW chatbang (browser ChatGPT) — not your manual copy/paste session."
echo "Progress: [governor collab] on stderr. Chatbang reply may take 2–10 min; Cursor 10–30+ min."
echo "v1.8: human-only + JSON contract; stops on Chatbang fail/timeout (no fake CONTINUE)."
echo "Pre-flight (product repo): bash scripts/verify_light.sh && bash scripts/run_b01_stability.sh"
echo "RAM: use scripts/verification_watchdog.sh run -- bash scripts/verify_linux.sh (never background verify without watchdog)."
echo "Product repo: $VA_REPO"
echo "Seed: $SEED_FILE"
cat "$SEED_FILE" > "$SEED_COMBINED"
if [[ -f "$PASS_CRITERIA" ]]; then
  cat "$PASS_CRITERIA" >> "$SEED_COMBINED"
fi

python -m governor collab start \
  --task "Voice assistant quality — Maximum Aggressive Offer Mode" \
  --chatbang-seed-file "$SEED_COMBINED" \
  --chatbang-human-only \
  --max-rounds 5 \
  --executor-profile cursor-headless-local \
  --autopilot \
  --audit-after \
  --auditor-profile cursor-headless-local \
  --commit-policy if_gates_pass \
  --continue-on-gate-warn \
  --chatbang-timeout 900 \
  --executor-timeout 3600 \
  --repo-path "$VA_REPO" \
  2>&1 | tee "/tmp/governor_collab_$(date -u +%Y%m%dT%H%M%SZ).log"

SESSION_DIR="$(ls -td "$VA_REPO/.governor/collab/"*_collab_voice-assistant-quality-maximum-aggressive-offer 2>/dev/null | head -1 || true)"
if [[ -n "$SESSION_DIR" ]]; then
  echo
  echo "==> collab + product eval"
  python "$GOV_ROOT/scripts/eval_collab_session.py" \
    --session-root "$SESSION_DIR" \
    --verification-summary "$VA_REPO/offer_engine/reports/latest/verification_summary.json" || true
fi
