# WordPress High-Risk Answer-Key Scorecard

- Run: `wordpress-performance-critic-regenerated-focused-answer-key-20260621`
- Created: `2026-06-21T09:21:24Z`
- Suites: `wordpress-performance-critic`
- Conditions: `skill`, `baseline-zero-shot`, `baseline-few-shot`

## Boundary

Deterministic lexical answer-key coverage over archived saved outputs. It uses rubric domain_signals for must-detect items, expected WordPress APIs, and must-not-claim anti-patterns. It is not semantic LLM judging, human review, variance measurement, runtime proof, or benchmark superiority evidence.

## Suite And Condition Means

| Suite | Condition | n | Recall | API coverage | Specificity | Composite |
|---|---:|---:|---:|---:|---:|---:|
| wordpress-performance-critic | baseline-few-shot | 3 | 1.000 | 0.585 | 1.000 | 0.862 |
| wordpress-performance-critic | baseline-zero-shot | 3 | 0.917 | 0.619 | 1.000 | 0.845 |
| wordpress-performance-critic | skill | 3 | 0.917 | 0.830 | 1.000 | 0.915 |

## Per-Fixture Scores

- `wordpress-performance-critic` / `autoload-transient-invalidation-v1` / `skill`: composite `0.880`, recall `0.750`, API `0.889`, specificity `1.000`
- `wordpress-performance-critic` / `autoload-transient-invalidation-v1` / `baseline-zero-shot`: composite `0.852`, recall `1.000`, API `0.556`, specificity `1.000`
- `wordpress-performance-critic` / `autoload-transient-invalidation-v1` / `baseline-few-shot`: composite `0.852`, recall `1.000`, API `0.556`, specificity `1.000`
- `wordpress-performance-critic` / `frontend-assets-render-path-v1` / `skill`: composite `0.933`, recall `1.000`, API `0.800`, specificity `1.000`
- `wordpress-performance-critic` / `frontend-assets-render-path-v1` / `baseline-zero-shot`: composite `0.817`, recall `0.750`, API `0.700`, specificity `1.000`
- `wordpress-performance-critic` / `frontend-assets-render-path-v1` / `baseline-few-shot`: composite `0.833`, recall `1.000`, API `0.500`, specificity `1.000`
- `wordpress-performance-critic` / `query-cache-pressure-v1` / `skill`: composite `0.933`, recall `1.000`, API `0.800`, specificity `1.000`
- `wordpress-performance-critic` / `query-cache-pressure-v1` / `baseline-zero-shot`: composite `0.867`, recall `1.000`, API `0.600`, specificity `1.000`
- `wordpress-performance-critic` / `query-cache-pressure-v1` / `baseline-few-shot`: composite `0.900`, recall `1.000`, API `0.700`, specificity `1.000`

## Not Claimed

- This does not replace QA/test-critic review.
- This does not prove finding quality, exploitability, production impact, or migration readiness.
- This does not prove the skill lanes outperform current ChatGPT-level baselines.
- This does not score `wordpress-blueprint-executor`; that lane still needs a recorded Playground launch smoke before runtime claims.
