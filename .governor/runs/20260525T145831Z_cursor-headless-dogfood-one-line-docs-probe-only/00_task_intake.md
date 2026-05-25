# Task intake

**Run ID:** `20260525T145831Z_cursor-headless-dogfood-one-line-docs-probe-only`  
**Task:** Cursor headless dogfood: one-line docs probe only  
**Target repo:** `/home/shevchenkool/project/Engineering-agent-governor`  
**Policy:** `docs` — Documentation-only changes; accuracy and examples over code gates.

## Objective

Cursor headless dogfood: one-line docs probe only

## Policy: docs

Documentation-only changes; accuracy and examples over code gates.

## Acceptance criteria

- [ ] Documentation accurate vs current code/CLI
- [ ] Examples runnable or clearly marked illustrative
- [ ] No product code changes unless required for doc build

## Constraints

- Minimal scope aligned with policy `docs`
- Governor applies lightweight redaction only. Logs and artifacts may still contain sensitive data. Do not paste secrets into recorded outputs.
- Human delegates implementation; Governor records and gates only

## Evidence expectations

- No product code changes unless necessary for doc build
- Validator confirms accuracy and working examples
- Links and version references updated

## Out of scope

- (list explicitly)

## References

- (links, tickets, docs)
