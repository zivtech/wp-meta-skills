# Pilot Results

Status: focused saved-output contract evidence, deterministic answer-key
coverage, and main-agent QA review exist; not benchmark mature.

The suite now has the original smoke fixture plus four focused fixtures:

- `rest-ajax-authorization-v1`
- `input-sql-output-handling-v1`
- `upload-filesystem-boundary-v1`
- `security-gate-consumption-v1`

Current evidence:

- Fixture, metadata, and rubric files exist for each focused fixture.
- Strict suite integrity validation passes for `wordpress-security-critic`.
- Saved-output run:
  `evals/results/wordpress-security-critic-saved-outputs-20260621/`.
- Generation succeeded for 12/12 outputs across `skill`,
  `baseline-zero-shot`, and `baseline-few-shot`.
- Deterministic output-contract oracle results exist for every saved output.
- Focused `skill` outputs from the 2026-06-21 saved run passed the output
  contract 3/3:
  `rest-ajax-authorization-v1`, `input-sql-output-handling-v1`, and
  `upload-filesystem-boundary-v1`.
- `security-gate-consumption-v1` was added after that run and needs a fresh
  saved-output pass before it is included in score claims.
- Baseline outputs generated successfully but did not pass the strict
  skill-output contract. This is contract-adherence evidence only, not a quality
  benchmark.
- The legacy broad `smoke-wordpress-v1` skill output failed the strict output
  contract and remains diagnostic evidence rather than focused-suite proof.
- Deterministic answer-key coverage exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/`.
- Focused `skill` outputs scored composite `0.936`; `baseline-zero-shot`
  scored `0.806`; `baseline-few-shot` scored `0.862`.
- QA review exists at
  `evals/results/wordpress-high-risk-answer-key-20260621/qa-review.md`; it
  accepts this as internal diagnostic evidence with reservations and rejects
  public benchmark-superiority claims.

Still missing before benchmark or release-quality claims:

- Independent `test-critic`/QA review or manual semantic annotation of the
  suite design and scoring interpretation.

This suite remains experimental until those gates are run. It does not prove
production exploitability, supply-chain review, CVE monitoring, malware
scanning, semantic review quality, or accepted superiority over a current
baseline.
