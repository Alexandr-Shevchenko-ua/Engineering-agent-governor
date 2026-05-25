# Run plan

**Run ID:** `20260525T102440Z_audit-readme-and-cli-reference-consistency-for-v`
**Overall status:** FAIL
**Auto repair prepare on fail:** False
**Stop on gate WARN:** True
**Gate profile:** `fast`

| Step | Action | Status | Profile/Runner | Reason |
|------|--------|--------|----------------|--------|
| dispatch_executor | dispatch_executor | PASS | echo-test |  |
| gate | gate | FAIL | - | gate overall FAIL |
| dispatch_validator | dispatch_validator | PENDING | fake-validator |  |
| report | report | PENDING | - |  |

> Bounded orchestration — not autopilot. Dispatch steps require `--approve`.
> No automatic repair dispatch; repair prepare only on failure when enabled.
