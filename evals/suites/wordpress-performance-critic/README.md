# wordpress-performance-critic Focused Eval Scaffold

Focused evaluation scaffold for `wordpress-performance-critic`. The suite now
contains the original broad smoke fixture plus three focused performance
fixtures:

- `query-cache-pressure-v1`: `WP_Query` shape, avoidable count/cache costs,
  measurement discipline, and cache invalidation boundaries.
- `autoload-transient-invalidation-v1`: option/autoload pressure, transient
  lifetime, invalidation triggers, and render-time remote call fallback.
- `frontend-assets-render-path-v1`: frontend asset loading, editor/frontend
  asset boundaries, dynamic render callbacks, and browser/performance
  measurement.

This is not a benchmark result yet. A saved-output contract run and
deterministic answer-key coverage now exist, but `test-critic` or QA review is
still required before making a public benchmark claim.

Saved-output evidence:

- Run: `evals/results/wordpress-performance-critic-saved-outputs-20260621/`
- Generation: `12/12` outputs archived across `skill`,
  `baseline-zero-shot`, and `baseline-few-shot`
- Contract archives: `12/12` deterministic output-contract results written
- Focused skill subset: `3/3` non-smoke skill outputs passed the
  `wordpress-performance-critic` output contract
- Baselines: generated, but `0/8` baseline outputs passed the strict
  skill-output contract
- Legacy smoke: generated, and the skill output passed the strict contract

Answer-key coverage evidence:

- Run: `evals/results/wordpress-high-risk-answer-key-20260621/`
- Focused `skill` outputs scored composite `0.844`, with recall `0.667`, API
  coverage `0.867`, and conservative specificity `1.000`.
- `baseline-zero-shot` also scored composite `0.844`; `baseline-few-shot`
  scored `0.791`.
- This does not show a lexical answer-key edge for the skill lane. It does show
  higher WordPress API coverage than either baseline under this deterministic
  instrument.
- Scoped semantic annotation for `query-cache-pressure-v1` exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/performance-query-cache-semantic-annotation.md`.
  It records the archived skill output as semantically `3/4` on must-detect
  items while preserving the custom-table scale-evidence gap and the unchanged
  archived scores.
- Regenerated post-repair output for `query-cache-pressure-v1` exists at
  `evals/results/wordpress-performance-critic-query-cache-regenerated-20260621/`.
  The regenerated skill output passed the output contract `1/1`.
- Deterministic answer-key coverage for that regenerated output exists at
  `evals/results/wordpress-performance-critic-query-cache-regenerated-answer-key-20260621/`.
  It scored recall `1.000`, API coverage `0.700`, specificity `1.000`, and
  composite `0.900` on this one fixture.
- Full focused post-repair regeneration exists at
  `evals/results/wordpress-performance-critic-regenerated-focused-20260621/`.
  Generation passed `9/9` across `skill`, `baseline-zero-shot`, and
  `baseline-few-shot`; focused skill outputs passed the output contract `3/3`,
  while baseline lanes remained `0/6` on the strict skill-output contract.
- Deterministic answer-key coverage for the regenerated focused run exists at
  `evals/results/wordpress-performance-critic-regenerated-focused-answer-key-20260621/`.
  Condition composites were `skill` `0.915`, `baseline-zero-shot` `0.845`, and
  `baseline-few-shot` `0.862`. This is directional lexical/contract evidence,
  not accepted benchmark evidence.

Output contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-performance-critic \
  --output <candidate-output.md>
```

Strict suite integrity gate:

```bash
python3 scripts/validate-eval-suite-integrity.py \
  --strict-suites wordpress-performance-critic \
  --allow-known-gaps
```

Negative space:

- This suite does not prove production latency, production capacity, Core Web
  Vitals failure, or cache effectiveness without real measurement data.
- This suite does not prove `wordpress-performance-critic` outperforms a
  current ChatGPT-level baseline until review evidence exists and the
  answer-key interpretation is accepted.
- The scoped semantic annotation and regenerated one-fixture run are not
  independent QA/test-critic review, long-run variance evidence, or a
  baseline-superiority claim. The regenerated focused run reduces the
  full-suite regeneration gap for this suite, but it still needs independent
  review before public benchmark claims.
- This suite is focused on WordPress performance review output quality, not
  runtime profiling by itself.
