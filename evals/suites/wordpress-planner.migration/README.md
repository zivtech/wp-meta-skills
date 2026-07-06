# wordpress-planner.migration Focused Eval Scaffold

Focused evaluation scaffold for `wordpress-planner.migration`. The suite now
contains the original broad smoke fixture plus three focused migration planning
fixtures:

- `legacy-cms-content-mapping-v1`: source schema uncertainty, post type and
  taxonomy mapping, author/byline handling, media relationships, and field
  transforms.
- `url-redirect-permalink-v1`: permalink model, redirect-map acceptance
  criteria, crawl comparison, query-string handling, and 404 sampling.
- `cutover-rollback-reconciliation-v1`: dry-run findings, delta migration,
  rollback triggers, reconciliation queues, and launch ownership.

This is not a benchmark result. Saved skill and baseline outputs plus
deterministic output-contract results exist at
`evals/results/wordpress-planner-migration-saved-outputs-20260621/`; generation
passed for 12/12 outputs, all four skill outputs passed the deterministic
output contract, and the three focused skill outputs passed 3/3. Deterministic
answer-key coverage now exists at
`evals/results/wordpress-high-risk-answer-key-20260621/`; focused `skill`
outputs scored composite `0.954`, `baseline-zero-shot` scored `0.861`, and
`baseline-few-shot` scored `0.926`. `test-critic` or QA review is still
required before making any public benchmark claim.

Output contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-planner.migration \
  --output <candidate-output.md>
```

Strict suite integrity gate:

```bash
python3 scripts/validate-eval-suite-integrity.py \
  --strict-suites wordpress-planner.migration \
  --allow-known-gaps
```

Negative space:

- This suite does not prove a real migration without source extracts,
  stakeholder acceptance criteria, dry-run outputs, and launch signoff.
- This suite does not prove `wordpress-planner.migration` outperforms a current
  ChatGPT-level baseline until review evidence exists and the answer-key
  interpretation is accepted.
- This suite is focused on migration plan quality, not executing a migration.
