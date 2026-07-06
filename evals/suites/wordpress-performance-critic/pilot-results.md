# Pilot Results

Status: focused saved-output contract evidence, deterministic answer-key
coverage, and main-agent QA review exist; not benchmark mature.

The suite now has the original smoke fixture plus three focused fixtures:

- `query-cache-pressure-v1`
- `autoload-transient-invalidation-v1`
- `frontend-assets-render-path-v1`

Current evidence:

- Fixture, metadata, and rubric files exist for each focused fixture.
- Strict suite integrity validation passes for `wordpress-performance-critic`.
- Saved skill and baseline outputs exist at
  `evals/results/wordpress-performance-critic-saved-outputs-20260621/`.
- Generation passed for `12/12` outputs across `skill`,
  `baseline-zero-shot`, and `baseline-few-shot`.
- Deterministic output-contract archives exist for every saved output.
- The three focused skill outputs passed the output contract `3/3`; the legacy
  smoke skill output also passed.
- Baseline lanes generated but did not pass the strict skill-output contract.
- Deterministic answer-key coverage exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/`.
- Focused `skill` outputs scored composite `0.844`, tying
  `baseline-zero-shot` (`0.844`) and ahead of `baseline-few-shot` (`0.791`).
- Under this lexical instrument, the skill lane had higher API coverage
  (`0.867`) but lower recall (`0.667`) than `baseline-zero-shot` (`0.615` API,
  `0.917` recall).
- QA review exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/qa-review.md`; it
  rejects any performance-superiority claim and flags
  `query-cache-pressure-v1` for follow-up recall review.
- Follow-up recall review exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/performance-query-cache-recall-review.md`.
  It found one semantic scorer miss around measurement language and one real
  archived-output gap around the custom-table scale evidence boundary. The
  performance critic prompt was amended for future generations without
  changing archived scores.
- Scoped semantic annotation exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/performance-query-cache-semantic-annotation.md`.
  It records the archived `query-cache-pressure-v1` skill output as
  semantically `3/4` on must-detect items, with the custom-table scale-evidence
  boundary still missing. This is main-agent annotation, not independent
  benchmark review.
- Regenerated post-repair output exists at
  `evals/results/wordpress-performance-critic-query-cache-regenerated-20260621/`.
  The regenerated `query-cache-pressure-v1` skill output passed the output
  contract `1/1`.
- Deterministic answer-key coverage for the regenerated output exists at
  `evals/results/wordpress-performance-critic-query-cache-regenerated-answer-key-20260621/`.
  It scored recall `1.000`, API coverage `0.700`, specificity `1.000`, and
  composite `0.900` for this single fixture.
- Full focused post-repair regeneration exists at
  `evals/results/wordpress-performance-critic-regenerated-focused-20260621/`.
  Generation passed `9/9` across `skill`, `baseline-zero-shot`, and
  `baseline-few-shot`; focused skill outputs passed the output contract `3/3`,
  and baseline lanes remained `0/6` on the strict skill-output contract.
- Deterministic answer-key coverage for the regenerated focused run exists at
  `evals/results/wordpress-performance-critic-regenerated-focused-answer-key-20260621/`.
  Condition composites were `skill` `0.915`, `baseline-zero-shot` `0.845`, and
  `baseline-few-shot` `0.862`. The regenerated skill lane has higher composite
  and API coverage under this lexical instrument, but this is still not
  accepted benchmark evidence.

Still missing before benchmark or release-quality claims:

- Independent `test-critic`/QA review of the suite design and scoring
  interpretation, plus any long-run variance measurement needed before a
  public benchmark claim.

This suite remains experimental until those remaining gates are run. It does
not prove production latency, production capacity, Core Web Vitals failure,
cache effectiveness, semantic review quality, long-run variance reduction, or
superiority over a current baseline.
