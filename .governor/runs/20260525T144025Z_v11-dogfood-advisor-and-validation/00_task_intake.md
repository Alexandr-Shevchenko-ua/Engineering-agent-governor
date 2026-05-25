# Task intake

**Run ID:** `20260525T144025Z_v11-dogfood-advisor-and-validation`  
**Task:** v1.1 dogfood advisor and validation  
**Target repo:** `/home/shevchenkool/project/Engineering-agent-governor`  
**Policy:** `agentic-tooling` — Governor/agent harness changes; guard against autopilot and secret leakage.

## Objective

v1.1 dogfood advisor and validation

## Policy: agentic-tooling

Governor/agent harness changes; guard against autopilot and secret leakage.

## Acceptance criteria

- [ ] No autopilot, background jobs, or auto repair dispatch loops
- [ ] No merge/push/deploy automation in governor
- [ ] No hardcoded vendor agent CLI syntax in core
- [ ] `.governor` remains gitignored

## Constraints

- Minimal scope aligned with policy `agentic-tooling`
- Governor applies lightweight redaction only. Logs and artifacts may still contain sensitive data. Do not paste secrets into recorded outputs.
- Human delegates implementation; Governor records and gates only

## Evidence expectations

- No merge/push/deploy automation added
- No external LLM API calls in governor core
- `.governor` remains gitignored
- Explicit --approve preserved for dispatch

## Out of scope

- (list explicitly)

## References

- (links, tickets, docs)
