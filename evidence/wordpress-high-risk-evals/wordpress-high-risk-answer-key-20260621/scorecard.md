# WordPress High-Risk Answer-Key Scorecard

- Run: `wordpress-high-risk-answer-key-20260621`
- Created: `2026-06-21T08:15:32Z`
- Suites: `wordpress-performance-critic`, `wordpress-planner.migration`, `wordpress-security-critic`
- Conditions: `skill`, `baseline-zero-shot`, `baseline-few-shot`

## Boundary

Deterministic lexical answer-key coverage over archived saved outputs. It uses rubric domain_signals for must-detect items, expected WordPress APIs, and must-not-claim anti-patterns. It is not semantic LLM judging, human review, variance measurement, runtime proof, or benchmark superiority evidence.

## Suite And Condition Means

| Suite | Condition | n | Recall | API coverage | Specificity | Composite |
|---|---:|---:|---:|---:|---:|---:|
| wordpress-performance-critic | baseline-few-shot | 3 | 0.750 | 0.622 | 1.000 | 0.791 |
| wordpress-performance-critic | baseline-zero-shot | 3 | 0.917 | 0.615 | 1.000 | 0.844 |
| wordpress-performance-critic | skill | 3 | 0.667 | 0.867 | 1.000 | 0.844 |
| wordpress-planner.migration | baseline-few-shot | 3 | 0.917 | 0.861 | 1.000 | 0.926 |
| wordpress-planner.migration | baseline-zero-shot | 3 | 0.750 | 0.944 | 0.889 | 0.861 |
| wordpress-planner.migration | skill | 3 | 0.917 | 0.944 | 1.000 | 0.954 |
| wordpress-security-critic | baseline-few-shot | 3 | 0.917 | 0.669 | 1.000 | 0.862 |
| wordpress-security-critic | baseline-zero-shot | 3 | 0.833 | 0.695 | 0.889 | 0.806 |
| wordpress-security-critic | skill | 3 | 1.000 | 0.809 | 1.000 | 0.936 |

## Per-Fixture Scores

- `wordpress-security-critic` / `input-sql-output-handling-v1` / `skill`: composite `0.923`, recall `1.000`, API `0.769`, specificity `1.000`
- `wordpress-security-critic` / `input-sql-output-handling-v1` / `baseline-zero-shot`: composite `0.840`, recall `0.750`, API `0.769`, specificity `1.000`
- `wordpress-security-critic` / `input-sql-output-handling-v1` / `baseline-few-shot`: composite `0.897`, recall `1.000`, API `0.692`, specificity `1.000`
- `wordpress-security-critic` / `rest-ajax-authorization-v1` / `skill`: composite `0.933`, recall `1.000`, API `0.800`, specificity `1.000`
- `wordpress-security-critic` / `rest-ajax-authorization-v1` / `baseline-zero-shot`: composite `0.672`, recall `0.750`, API `0.600`, specificity `0.667`
- `wordpress-security-critic` / `rest-ajax-authorization-v1` / `baseline-few-shot`: composite `0.783`, recall `0.750`, API `0.600`, specificity `1.000`
- `wordpress-security-critic` / `upload-filesystem-boundary-v1` / `skill`: composite `0.952`, recall `1.000`, API `0.857`, specificity `1.000`
- `wordpress-security-critic` / `upload-filesystem-boundary-v1` / `baseline-zero-shot`: composite `0.905`, recall `1.000`, API `0.714`, specificity `1.000`
- `wordpress-security-critic` / `upload-filesystem-boundary-v1` / `baseline-few-shot`: composite `0.905`, recall `1.000`, API `0.714`, specificity `1.000`
- `wordpress-performance-critic` / `autoload-transient-invalidation-v1` / `skill`: composite `0.917`, recall `0.750`, API `1.000`, specificity `1.000`
- `wordpress-performance-critic` / `autoload-transient-invalidation-v1` / `baseline-zero-shot`: composite `0.815`, recall `1.000`, API `0.444`, specificity `1.000`
- `wordpress-performance-critic` / `autoload-transient-invalidation-v1` / `baseline-few-shot`: composite `0.889`, recall `1.000`, API `0.667`, specificity `1.000`
- `wordpress-performance-critic` / `frontend-assets-render-path-v1` / `skill`: composite `0.817`, recall `0.750`, API `0.700`, specificity `1.000`
- `wordpress-performance-critic` / `frontend-assets-render-path-v1` / `baseline-zero-shot`: composite `0.817`, recall `0.750`, API `0.700`, specificity `1.000`
- `wordpress-performance-critic` / `frontend-assets-render-path-v1` / `baseline-few-shot`: composite `0.750`, recall `0.750`, API `0.500`, specificity `1.000`
- `wordpress-performance-critic` / `query-cache-pressure-v1` / `skill`: composite `0.800`, recall `0.500`, API `0.900`, specificity `1.000`
- `wordpress-performance-critic` / `query-cache-pressure-v1` / `baseline-zero-shot`: composite `0.900`, recall `1.000`, API `0.700`, specificity `1.000`
- `wordpress-performance-critic` / `query-cache-pressure-v1` / `baseline-few-shot`: composite `0.733`, recall `0.500`, API `0.700`, specificity `1.000`
- `wordpress-planner.migration` / `cutover-rollback-reconciliation-v1` / `skill`: composite `0.944`, recall `1.000`, API `0.833`, specificity `1.000`
- `wordpress-planner.migration` / `cutover-rollback-reconciliation-v1` / `baseline-zero-shot`: composite `0.944`, recall `1.000`, API `0.833`, specificity `1.000`
- `wordpress-planner.migration` / `cutover-rollback-reconciliation-v1` / `baseline-few-shot`: composite `0.944`, recall `1.000`, API `0.833`, specificity `1.000`
- `wordpress-planner.migration` / `legacy-cms-content-mapping-v1` / `skill`: composite `0.917`, recall `0.750`, API `1.000`, specificity `1.000`
- `wordpress-planner.migration` / `legacy-cms-content-mapping-v1` / `baseline-zero-shot`: composite `0.750`, recall `0.250`, API `1.000`, specificity `1.000`
- `wordpress-planner.migration` / `legacy-cms-content-mapping-v1` / `baseline-few-shot`: composite `0.917`, recall `0.750`, API `1.000`, specificity `1.000`
- `wordpress-planner.migration` / `url-redirect-permalink-v1` / `skill`: composite `1.000`, recall `1.000`, API `1.000`, specificity `1.000`
- `wordpress-planner.migration` / `url-redirect-permalink-v1` / `baseline-zero-shot`: composite `0.889`, recall `1.000`, API `1.000`, specificity `0.667`
- `wordpress-planner.migration` / `url-redirect-permalink-v1` / `baseline-few-shot`: composite `0.917`, recall `1.000`, API `0.750`, specificity `1.000`

## Not Claimed

- This does not replace QA/test-critic review.
- This does not prove finding quality, exploitability, production impact, or migration readiness.
- This does not prove the skill lanes outperform current ChatGPT-level baselines.
- This does not score `wordpress-blueprint-executor`; that lane still needs a recorded Playground launch smoke before runtime claims.
