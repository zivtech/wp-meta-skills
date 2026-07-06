# Performance Query-Cache Recall Follow-Up

- Review date: 2026-06-21
- Fixture: `wordpress-performance-critic` / `query-cache-pressure-v1`
- Source run: `wordpress-high-risk-answer-key-20260621`
- Related QA review: `qa-review.md`

## Verdict

The answer-key recall miss is mixed:

- `measurement is required before claiming performance impact` is a semantic
  pass but a lexical scorer miss.
- `custom tables require scale evidence` is a real output gap in the archived
  skill response.

Do not rewrite the archived scorecard. The current skill output remains recall
`0.500` for this fixture until a future saved-output rerun proves the amended
prompt changes behavior.

## Evidence

The archived skill output names measurement uncertainty and negative space:

- It lists "`Uncertain without measurement`" for topic cardinality, meta index
  state, and object-cache presence.
- It tells the reviewer to "Measure first" before treating the finding as a
  production incident.
- It says the verdict does not prove measured production latency.

The lexical answer-key scorer missed this because `item_detected()` uses token
overlap against the phrase `measurement is required before claiming performance
impact`. The output used different wording with similar meaning.

The archived skill output does not explicitly discuss custom tables. The rubric
and fixture both require the boundary that custom tables need scale evidence
and should not be recommended by default. That omission is real: the output did
not recommend custom tables, but it also did not name the negative-space
boundary the fixture asked for.

## Decision

Keep the answer-key score unchanged and amend the performance critic prompt so
future query/cache reviews must explicitly say:

- `measurement is required before claiming production impact`
- `custom tables require scale evidence`

This is a prompt-contract repair, not retroactive evidence repair. Future
evidence should regenerate the focused saved output before claiming improved
recall.

## Not Claimed

- This does not prove the performance critic now outperforms the baseline.
- This does not prove the amended prompt will change live model behavior.
- This does not change the published composite scores for
  `wordpress-high-risk-answer-key-20260621`.
- This does not close the need for independent/semantic benchmark review.
