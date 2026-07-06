# Performance Query-Cache Semantic Annotation

- Review date: 2026-06-21
- Fixture: `wordpress-performance-critic` / `query-cache-pressure-v1`
- Source run: `wordpress-high-risk-answer-key-20260621`
- Saved-output run: `wordpress-performance-critic-saved-outputs-20260621`
- Related artifacts: `scorecard.md`, `qa-review.md`, `performance-query-cache-recall-review.md`

## Scope

This is a bounded main-agent semantic annotation of one focused performance
fixture across the archived `skill`, `baseline-zero-shot`, and
`baseline-few-shot` responses. It exists to separate lexical scorer behavior
from semantic output quality for the known `query-cache-pressure-v1` recall
miss.

This is not independent QA/test-critic review, a regenerated saved-output run,
semantic LLM judging, or benchmark-superiority evidence.

## Annotation Verdict

The archived `skill` output is semantically stronger than its lexical recall
score suggests, but it still has a real boundary omission.

- Lexical answer-key score for `skill`: recall `0.500`, API coverage `0.900`,
  specificity `1.000`, composite `0.800`.
- Semantic annotation for `skill`: `3/4` must-detect items satisfied.
- The lexical scorer missed semantically equivalent measurement-discipline
  language in the `skill` output.
- The missing custom-table scale-evidence boundary is a real `skill` output
  gap.
- `baseline-zero-shot` is semantically `4/4` on must-detect items for this
  fixture and remains the strongest archived response on this specific
  semantic slice.
- `baseline-few-shot` is semantically `3/4` on must-detect items if its
  cache-invalidation language is credited, but it still omits the custom-table
  scale-evidence boundary.

Do not claim the performance critic improved recall until a future saved-output
run or independent annotation confirms the amended prompt behavior.

## Must-Detect Annotation

| Condition | Lexical recall | Semantic must-detect | Notes |
|---|---:|---:|---|
| `skill` | `0.500` | `3/4` | Detects N+1 query pressure; requires measurement before production-impact claims using different wording; gives cache key and invalidation guidance; omits explicit custom-table scale-evidence boundary. |
| `baseline-zero-shot` | `1.000` | `4/4` | Detects N+1 pressure, measurement discipline, cache invalidation/key design, and explicitly says not to jump directly to custom tables before evidence. |
| `baseline-few-shot` | `0.500` | `3/4` | Detects N+1 pressure and measurement discipline; credits cache invalidation because it asks what events invalidate cached output; omits the custom-table scale-evidence boundary. |

## API/Surface Annotation

The archived `skill` output matched 9 of 10 expected WordPress/API/tool
surfaces in the deterministic answer-key run:

- Matched: `WP_Query`, `no_found_rows`, `fields => 'ids'`,
  `update_post_meta_cache`, `update_post_term_cache`, `wp_cache_get`,
  `wp_cache_set`, `Query Monitor`, and `WP-CLI`.
- Lexically missing: `pre_get_posts`.

The `pre_get_posts` miss should not be treated as a severe quality issue for
this fixture. The saved `skill` response reviews a direct custom `WP_Query`
inside a render function; naming `pre_get_posts` as a primary remediation would
be less appropriate than direct query-argument changes. The fixture asked to
name `pre_get_posts` only where appropriate, so the miss is a measurement
limitation rather than a clear response defect.

The `baseline-zero-shot` and `baseline-few-shot` responses both matched 7 of 10
expected surfaces and missed `wp_cache_get`, `wp_cache_set`, and `WP-CLI`.

## Boundary Annotation

All three archived responses avoid the major anti-claims:

- none claim that all `WP_Query` usage is a defect;
- none claim production latency is proven;
- none claim custom tables are mandatory without scale evidence.

The `skill` output goes further on production-impact negative space by saying
the verdict does not prove current production latency and that impact depends
on topic count, table size, request frequency, and caching.

The `skill` output still fails the fixture's explicit negative-space request
because it does not name the custom-table boundary. It does not recommend
custom tables, but it also does not say that custom tables require scale
evidence.

## Decision

Keep the deterministic answer-key scores unchanged. Record this annotation as
qualitative evidence that the performance query/cache lexical recall miss
over-penalized measurement-discipline wording but correctly exposed a
custom-table boundary gap.

The next stronger evidence step is one of:

- regenerate the focused `query-cache-pressure-v1` saved output after the
  prompt repair and rerun deterministic scoring;
- obtain independent QA/test-critic review of the high-risk answer-key run;
- add a small independent semantic annotation sample across the security,
  performance, and migration focused fixtures.

## Not Claimed

- This does not prove performance-superiority over `baseline-zero-shot`.
- This does not prove the amended prompt changes future model behavior.
- This does not replace independent review.
- This does not change archived scorecard values.
- This does not close benchmark maturity for `wordpress-performance-critic`.
