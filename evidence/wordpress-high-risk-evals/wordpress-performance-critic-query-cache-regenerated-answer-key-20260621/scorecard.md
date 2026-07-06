# WordPress High-Risk Answer-Key Scorecard

- Run: `wordpress-performance-critic-query-cache-regenerated-answer-key-20260621`
- Created: `2026-06-21T09:04:53Z`
- Suites: `wordpress-performance-critic`
- Conditions: `skill`

## Boundary

Deterministic lexical answer-key coverage over archived saved outputs. It uses rubric domain_signals for must-detect items, expected WordPress APIs, and must-not-claim anti-patterns. It is not semantic LLM judging, human review, variance measurement, runtime proof, or benchmark superiority evidence.

## Suite And Condition Means

| Suite | Condition | n | Recall | API coverage | Specificity | Composite |
|---|---:|---:|---:|---:|---:|---:|
| wordpress-performance-critic | skill | 1 | 1.000 | 0.700 | 1.000 | 0.900 |

## Per-Fixture Scores

- `wordpress-performance-critic` / `query-cache-pressure-v1` / `skill`: composite `0.900`, recall `1.000`, API `0.700`, specificity `1.000`

## Not Claimed

- This does not replace QA/test-critic review.
- This does not prove finding quality, exploitability, production impact, or migration readiness.
- This does not prove the skill lanes outperform current ChatGPT-level baselines.
- This does not score `wordpress-blueprint-executor`; that lane still needs a recorded Playground launch smoke before runtime claims.
