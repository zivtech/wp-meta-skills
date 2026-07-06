# wordpress-security-critic Focused Eval Scaffold

Focused evaluation scaffold for `wordpress-security-critic`. The suite now
contains the original broad smoke fixture plus four focused security fixtures:

- `rest-ajax-authorization-v1`: REST/AJAX mutation authorization, nonce
  calibration, `wp_ajax_nopriv_*`, and forbidden-role test paths.
- `input-sql-output-handling-v1`: unslashed request input, interpolated SQL,
  context-specific escaping, and sanitization-vs-escaping calibration.
- `upload-filesystem-boundary-v1`: upload validation, executable file paths,
  local include/copy behavior, path traversal, and capability/nonce pairing.
- `security-gate-consumption-v1`: deterministic `security-gate.json` evidence
  consumption, suppression-diff review, and gate-derived vs critic-derived
  provenance.

This is not a benchmark result yet. A saved-output contract run now exists at
`evals/results/wordpress-security-critic-saved-outputs-20260621/`:

- Generation succeeded for 12/12 outputs across `skill`,
  `baseline-zero-shot`, and `baseline-few-shot`.
- The three focused `skill` outputs passed the deterministic output contract
  3/3.
- The legacy broad smoke `skill` output failed the output contract and remains
  diagnostic evidence, not focused-suite proof.
- Baseline lanes generated successfully but did not pass the strict
  skill-output contract.

Deterministic answer-key coverage now exists at
`evals/results/wordpress-high-risk-answer-key-20260621/`:

- Focused `skill` outputs scored composite `0.936` across the three non-smoke
  fixtures, with recall `1.000`, API coverage `0.809`, and conservative
  specificity `1.000`.
- `baseline-zero-shot` scored composite `0.806`; `baseline-few-shot` scored
  composite `0.862`.

This is lexical answer-key coverage, not semantic judge scoring. `test-critic`
or QA review is still required before making a public benchmark claim.

Output contract oracle:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-security-critic \
  --output <candidate-output.md>
```

When a real sidecar is available, require the security critic to consume it:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-security-critic \
  --output <candidate-output.md> \
  --security-gate <security-gate.json>
```

The saved-output runner auto-detects fixture sidecars named
`fixtures/<fixture>.security-gate.json`; the gate-consumption fixture uses
`fixtures/security-gate-consumption-v1.security-gate.json`.

Saved-output runner:

```bash
python3 evals/harness/run_wordpress_high_risk_saved_outputs.py \
  --suite wordpress-security-critic \
  --run-id wordpress-security-critic-saved-outputs-20260621 \
  --conditions skill,baseline-zero-shot,baseline-few-shot \
  --resume
```

Strict suite integrity gate:

```bash
python3 scripts/validate-eval-suite-integrity.py \
  --strict-suites wordpress-security-critic \
  --allow-known-gaps
```

Negative space:

- This suite does not prove supply-chain review, CVE monitoring, malware
  scanning, hosting-level executable-file policy, or production exploitability.
- This suite does not prove `wordpress-security-critic` outperforms a current
  ChatGPT-level baseline until review evidence exists and the answer-key
  interpretation is accepted.
- The 2026-06-21 saved-output evidence predates
  `security-gate-consumption-v1`; rerun saved outputs before claiming coverage
  for the new gate-consumption fixture.
- This suite is focused on WordPress security review output quality, not runtime
  exploit execution.
