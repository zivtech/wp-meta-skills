# WordPress Skill Candidate Eval

This suite evaluates WordPress skill candidates before adopting or adapting upstream material. It has 27 discovery fixtures across 9 WordPress domains and 3 tiers, plus 5 adversarial answer-key diagnostic fixtures.

This suite is not a completed benchmark result. The original pilot design was approved for execution by the local `test-critic` review in `test-critic-review.md`; subsequent pairwise and answer-key diagnostics closed the frontier-model review-quality arc as directional-internal only.

Candidate screening result: `evals/results/wordpress-skill-candidate-eval/2026-06-16-candidate-screening.md`.
Pilot runbook: `wordpress-skills/docs/candidate-pilot-runbook.md`.

The v1 absolute-scoring pilot failed (it did not separate known-weak and
known-strong by 0.2; archived in `wordpress-candidate-pilot-20260616-live/`). The
suite was redesigned around **blind pairwise preference** + an escalate-first
validity gate + a 3-way AC1 reliability gate + generation isolation + a frozen
pre-registration (`pairwise-prereg.md`; build + GATE 1 record in
`pairwise-build-summary.md`).

Current best internal evidence:

- Pairwise pilot/cert runs (`pairwise-pilot-20260617-061925/`, `pairwise-cert-1/`,
  `pairwise-cert-2-xfamily/`) closed as **directional-internal only**. Zivtech is
  top-tier, but not certified and not reliably separated from a strong few-shot prompt.
- Answer-key diagnostics (`answerkey-diag-fast/`, `answerkey-diag-adversarial/`)
  found no detection or false-positive-control edge on Sonnet-generated review tasks.
  The measurable gap is exact WordPress API naming.
- The first cheaper-model diagnostic (`answerkey-haiku-adversarial-fast-20260620/`)
  did not rescue the per-task review-quality claim. Haiku generation showed a strong
  Zivtech block-deprecation win, but no broad lift over zero-shot or few-shot prompts.
- The Exact API contract gate (`scripts/validate-wordpress-exact-api-contract.py`)
  now fails if WordPress prompts lose the contract or if `expected_wordpress_apis`
  drift back to generic category labels.
- Decision: keep the Zivtech V1 lifecycle scaffold, do not adopt upstream wholesale,
  and do not make a superiority claim. See `pairwise-cert-2-xfamily/INTERNAL-DECISION-FINAL.md`
  and `answerkey-diag-adversarial/RESULT-INTERPRETATION.md`.

Full benchmark execution remains blocked: do not run the 27-fixture benchmark for a
frontier-model review-quality superiority claim. Reopen only for a changed target,
such as cheaper-model lift, output-contract conformance, variance reduction, or
executor/oracle-backed code generation.

For the output-contract target, validate saved outputs with:

```bash
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill <wordpress-skill> \
  --output <candidate-output.md>
```

Baseline prompts may fail this oracle. That is evidence only for contract adherence
or variance-reduction claims, not evidence that the skill has better per-task
review judgment on a frontier model.
