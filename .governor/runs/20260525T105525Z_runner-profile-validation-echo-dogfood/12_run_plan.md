# Run plan

**Run ID:** `20260525T105525Z_runner-profile-validation-echo-dogfood`
**Overall status:** PASS
**Auto repair prepare on fail:** False
**Stop on gate WARN:** True
**Gate profile:** `fast`

| Step | Action | Status | Profile/Runner | Reason |
|------|--------|--------|----------------|--------|
| dispatch_executor | dispatch_executor | PASS | echo-test |  |
| gate | gate | FAIL | - | gate overall WARN (stop_on_warn) |
| dispatch_validator | dispatch_validator | PASS | fake-validator |  |
| report | report | PASS | - |  |

> Bounded orchestration — not autopilot. Dispatch steps require `--approve`.
> No automatic repair dispatch; repair prepare only on failure when enabled.
