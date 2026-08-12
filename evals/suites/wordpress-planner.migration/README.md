# wordpress-planner.migration Focused Eval Scaffold

Focused evaluation scaffold for `wordpress-planner.migration`. The suite now
contains the original broad smoke fixture plus three focused migration planning
fixtures:

- `smoke-wordpress-v1`: an exact source-to-block contract for a repository-owned
  importer, including semantic block properties, unsupported-source accounting,
  byte-idempotent writes, and separate editor/frontend proof.
- `legacy-cms-content-mapping-v1`: source schema uncertainty, post type and
  taxonomy mapping, author/byline handling, media relationships, and field
  transforms.
- `url-redirect-permalink-v1`: permalink model, redirect-map acceptance
  criteria, crawl comparison, query-string handling, and 404 sampling.
- `cutover-rollback-reconciliation-v1`: dry-run findings, delta migration,
  rollback triggers, reconciliation queues, and launch ownership.

Historical saved outputs and answer-key diagnostics exist under `evals/results/`,
but they are directional internal evidence only. They do not establish a quality
edge over a current ChatGPT-level baseline and are not a public benchmark claim.
The fixture/rubric definitions in this suite describe planning expectations, not
proof that any migration was implemented or run.

For plans that affirmatively target Gutenberg, the saved-output oracle uses one
exact, duplicate-rejecting decision record per owning section. Record values are
enumerated by the smoke fixture and skill; negative-space prose and fenced
examples are not authoritative contract evidence. Non-Gutenberg plans do not
emit the Gutenberg-only records.

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
