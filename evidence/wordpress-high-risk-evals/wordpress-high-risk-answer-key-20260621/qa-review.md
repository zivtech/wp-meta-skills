# WordPress High-Risk Answer-Key QA Review

- Review date: 2026-06-21
- Reviewed run: `wordpress-high-risk-answer-key-20260621`
- Review scope: deterministic lexical answer-key scoring for focused
  `wordpress-security-critic`, `wordpress-performance-critic`, and
  `wordpress-planner.migration` saved outputs.
- Review mode: main-agent QA review. A callable `qa-critic` or subagent tool
  was not exposed in this Codex session, so this artifact should be superseded
  if an independent QA/test-critic review is later run.

## Verdict

ACCEPT-WITH-RESERVATIONS for internal diagnostic and evidence-boundary use.

REVISE before any public benchmark-superiority, release-quality, or semantic
review-quality claim.

The answer-key run is useful because it checks whether saved outputs mention
the rubric's expected risk classes, WordPress APIs, and exact forbidden claim
phrases. It is not strong enough to prove that findings are correct, complete,
or better than a current baseline.

## Evidence Inspected

- `evals/results/wordpress-high-risk-answer-key-20260621/scorecard.md`
- `evals/results/wordpress-high-risk-answer-key-20260621/answer-key-summary.json`
- `evals/harness/score_wordpress_high_risk_answer_keys.py`
- `evals/harness/tests/test_wordpress_high_risk_answer_keys.py`
- Focused suite rubrics under:
  - `evals/suites/wordpress-security-critic/rubrics/`
  - `evals/suites/wordpress-performance-critic/rubrics/`
  - `evals/suites/wordpress-planner.migration/rubrics/`
- Saved-output scorecards for:
  - `evals/results/wordpress-security-critic-saved-outputs-20260621/`
  - `evals/results/wordpress-performance-critic-saved-outputs-20260621/`
  - `evals/results/wordpress-planner-migration-saved-outputs-20260621/`

## Score Interpretation

| Suite | Skill composite | Best baseline composite | QA interpretation |
|---|---:|---:|---|
| `wordpress-security-critic` | `0.936` | `0.862` | Directionally useful lexical signal. Accept as partial diagnostic evidence, not exploitability or full security-review proof. |
| `wordpress-performance-critic` | `0.844` | `0.844` | No clean skill edge. The skill lane improves API coverage but has lower recall than `baseline-zero-shot`; use this as a repair target. |
| `wordpress-planner.migration` | `0.954` | `0.926` | Directionally useful lexical signal. Accept as partial diagnostic evidence, not real migration readiness or stakeholder acceptance proof. |

## Findings

### Major: The performance lane does not support a superiority claim

The `wordpress-performance-critic` skill lane tied `baseline-zero-shot` on
composite at `0.844`. It had higher API coverage (`0.867` vs. `0.615`) but
lower recall (`0.667` vs. `0.917`). The weakest fixture is
`query-cache-pressure-v1`, where the skill lane scored recall `0.500` and
composite `0.800`, while `baseline-zero-shot` scored recall `1.000` and
composite `0.900`.

Impact: performance evidence can support "the skill uses more exact WordPress
performance APIs" but not "the skill finds more of the expected issues" or
"the skill outperforms the baseline."

### Major: Recall is lexical token-overlap, not semantic correctness

`item_detected()` uses normalized token overlap with a default threshold of
`0.55`. That makes the run deterministic and cheap, but it can over-credit
responses that use matching vocabulary without making the right finding, and
it can under-credit correct paraphrases that use different wording.

Impact: the recall number is a coverage heuristic. It should not be treated as
human finding-quality review.

### Major: Specificity is exact anti-claim matching, not full overclaim review

`anti_claimed()` intentionally requires the exact normalized forbidden phrase
and ignores negated contexts. This avoids loose false positives, but it means
specificity primarily proves absence of exact forbidden phrases, not absence of
semantic overclaiming.

Impact: specificity `1.000` is a useful guardrail result, not a complete
negative-space review.

### Moderate: Security and migration results are useful but still partial

`wordpress-security-critic` and `wordpress-planner.migration` show stronger
directional lexical evidence than the baselines in this run. That is enough to
prioritize these lanes as more mature than pure smoke scaffolds. It is not
enough to claim production exploitability, real migration readiness, or
accepted human benchmark quality.

### Moderate: Baseline contract failures complicate baseline comparison

The focused skill outputs passed the deterministic output contract, while
baseline lanes generated successfully but did not pass the strict skill-output
contract. That supports a contract-adherence claim for the skill lane. It also
means baseline quality comparison is not clean: the answer-key run is comparing
archived baseline prose that may not share the same shape constraints.

## Accepted Uses

- State that deterministic lexical answer-key coverage now exists for the
  focused security, performance, and migration saved outputs.
- Use the security and migration scores as partial directional evidence that
  the focused fixtures are no longer just smoke scaffolds.
- Use the performance score as a diagnostic that the skill output needs recall
  review, especially on `query-cache-pressure-v1`.
- Bundle the review with the private `wp-meta-skills` standalone evidence.

## Rejected Uses

- Do not claim that the high-risk suites are benchmark mature.
- Do not claim the skills outperform a current ChatGPT-level baseline.
- Do not claim semantic review quality, production exploitability, production
  performance impact, migration readiness, or release readiness from this run.
- Do not use this review to close the Blueprint runtime gap; Blueprint still
  needs recorded WordPress Playground launch evidence before runtime claims.

## Required Follow-Up

1. Inspect the `wordpress-performance-critic` `query-cache-pressure-v1` skill
   output against the rubric and decide whether the output, rubric, or lexical
   scorer should change.
2. Add an independent QA/test-critic review or a small manual semantic review
   sample before any public benchmark claim.
3. If public benchmark claims matter, add semantic judging or human annotation
   with an agreement record instead of relying only on lexical coverage.
4. Keep the Blueprint lane blocked for runtime claims until a recorded
   Playground launch smoke exists.
5. Keep public standalone release blocked until PR #11 review/merge, standalone
   owner approval, public visibility approval, and cutover approval are done.

## Boundary

This review accepts the answer-key run as useful diagnostic evidence with
explicit limits. It does not make the WordPress suite "done," and it does not
replace owner review of the standalone `wp-meta-skills` repository.
