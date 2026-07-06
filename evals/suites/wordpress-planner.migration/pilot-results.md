# Pilot Results

Status: focused saved-output contract evidence, deterministic answer-key
coverage, and main-agent QA review exist; not benchmark mature.

The suite now has the original smoke fixture plus three focused fixtures:

- `legacy-cms-content-mapping-v1`
- `url-redirect-permalink-v1`
- `cutover-rollback-reconciliation-v1`

Current evidence:

- Fixture, metadata, and rubric files exist for each focused fixture.
- Strict suite integrity validation passes for `wordpress-planner.migration`.
- Saved skill and baseline outputs exist at
  `evals/results/wordpress-planner-migration-saved-outputs-20260621/`.
- Generation passed for `12/12` outputs across `skill`,
  `baseline-zero-shot`, and `baseline-few-shot`.
- Deterministic output-contract archives exist for every saved output.
- The three focused skill outputs passed the output contract `3/3`; the legacy
  smoke skill output also passed.
- Baseline lanes generated but did not pass the strict skill-output contract.
- Deterministic answer-key coverage exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/`.
- Focused `skill` outputs scored composite `0.954`; `baseline-zero-shot`
  scored `0.861`; `baseline-few-shot` scored `0.926`.
- QA review exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/qa-review.md`; it
  accepts this as internal diagnostic evidence with reservations and rejects
  real-migration-readiness or public benchmark claims.

Still missing before benchmark or release-quality claims:

- Independent `test-critic`/QA review or manual semantic annotation of the
  suite design and scoring interpretation.

This suite remains experimental until those remaining gates are run. It does
not prove a real migration, launch readiness, source-data fitness, or
accepted superiority over a current baseline.
