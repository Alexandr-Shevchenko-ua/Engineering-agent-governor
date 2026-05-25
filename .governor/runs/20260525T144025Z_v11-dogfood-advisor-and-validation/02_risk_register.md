# Risk register

**Policy:** `agentic-tooling`

| ID | Risk | Likelihood | Impact | Mitigation | Owner |
|----|------|------------|--------|------------|-------|
| R1 | Background execution or repair loops introduced | medium | medium | Mitigate per policy | owner |
| R2 | Hardcoded vendor CLI syntax | medium | medium | Mitigate per policy | owner |
| R3 | Secrets in config or artifacts | medium | medium | Mitigate per policy | owner |

## Stop conditions (policy)

- Autopilot or background daemon detected in diff
- Secret-like strings in committed config examples
- Cursor/Claude CLI syntax hardcoded in core

## Notes

- Update after gate and validator review.
