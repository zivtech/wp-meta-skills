# Critic Corpus — First Pilot Results (recommendation 09)

Date: 2026-08-11. Covers the answer-key corpus across the four critic suites. Read with
`corpus-prereg.md` (design) and `provenance-manifest.md` (sources). **This is an internal
diagnostic, not a benchmark or a superiority claim** (`CLAUDE.md` Evaluation Boundary).

## 1. What was built

A provenance-labeled answer-key corpus of **24 fixtures** (excluding the pre-existing smoke
fixtures), each a review target + `suite-risk`/`suite-smoke` metadata + `weighted-domain`
rubric + a `fixtures/<id>.provenance.yaml` sidecar:

| Suite | Tranche J (judgment) | Tranche C (clean/bait) | Tranche T (tool) |
| --- | ---: | ---: | ---: |
| wordpress-security-critic | 5 | 3 + 1(T-clean) | 4 |
| wordpress-performance-critic | 3 | 2 + 1(T-clean) | 1 |
| wordpress-critic (block) | 1 | 1 | 0 |
| wordpress-theme-critic | 1 | 1 | 0 |
| **total** | **10** | **9** | **5** |

The security tranche-J set is the discriminating core: IDOR on user meta, wrong-object
capability (`edit_posts` vs `edit_post,$id`), a discarded `wp_verify_nonce` return, a
decorative capability branch that does not gate the mutation, and a `LIKE` query missing
`$wpdb->esc_like`. The mandatory tranche-C trap — `permission_callback => '__return_true'`
on a genuinely public read-only endpoint — is present (same token as the BAC defect, opposite
correct verdict).

## 2. Verification status (all green)

- **Anti-leakage + provenance guard** (`test_critic_corpus_integrity.py`): 165 passed. No
  answer-key content leaks into any review target; every J fixture proves tool-invisibility;
  every C fixture is ACCEPT* with no `must_detect`; licenses are allowed; no non-commercial
  source; drafts stay out of the scored root.
- **Tool-invisibility gate** (`verify_critic_tool_invisibility.py`): every tranche-J PHP
  fixture runs through WPCS (WordPress standard) with **zero** security/perf sniffs firing,
  and was independently confirmed PHPStan-clean (level 4–5, `php-stubs/wordpress-stubs`). Two
  fixtures were caught mislabeled during this gate and corrected — an "open redirect" case
  that WPCS's `SafeRedirect` sniff *does* catch (replaced with the tool-invisible
  `esc_like` case) and an N+1 fixture whose incidental `meta_query` tripped `SlowDBQuery`
  (simplified so the query is silent). This is exactly the gate the prereg requires.
- **Frozen eval-suite validator** (`test_eval_suite_integrity.py`): 98 passed. Every new
  metadata/rubric matches an exact frozen profile; `eval.yaml` counts synced.
- **Harness unit tests**: `test_answer_key_score.py` (24, incl. 3 new pure-helper tests for
  grounding/severity-recall/false-positive-rate) and `test_build_cve_fixtures.py` (5) pass.
- **Distribution parity**: passed (15 skill/agent pairs). `MANIFEST.sha256` covers only
  distribution skill files, none of which changed, so no manifest regen is required.

Also of note: WPCS 3.3.0's `WordPress.WP.PostsPerPage` fires only on high positive literals
(>100), **not** on `posts_per_page => -1`, `nopaging => true`, or `numberposts => -1`. The
idiomatic unbounded patterns are therefore tool-invisible in the pinned toolchain and are
candidate tranche-J fixtures for a future round; the tranche-T PostsPerPage fixture uses a
high literal (500) that WPCS actually flags.

## 3. Instrument and pipeline — proven end to end

`answer_key_score.py` was generalized to be suite-aware (`--suite`, `--out`, strong=`skill` /
weak=`baseline-zero-shot`, per-tranche reports, tranche-C false-positive rate) with the
scoring math unchanged (I/O layer only; unit-tested). The generation + scoring pipeline runs:

- **Baseline lanes generate real reviews.** The zero-shot codex baseline on the IDOR fixture
  correctly localized the missing authorization to the `update_user_meta` call — evidence the
  fixtures are reviewable and the baseline is a live, non-trivial comparator, not a strawman.
- **Strong few-shot baselines** exist for all four suites (named dimensions, worked findings
  with file:line + reproduction, and a calibration non-finding). They still owe an independent
  reviewer's sanity check before any comparative reading is trusted (§10).

## 4. First three-condition judged run — results (2026-08-11)

A first `skill` / `baseline-zero-shot` / `baseline-few-shot` judged run ran over a security
slice — `sec-idor-user-meta-v1` (J), `sec-public-read-return-true-clean-v1` (C),
`t-escapeoutput-xss-v1` (T) — at runs=1 (`--fast`), primary judge `gpt-5.5`. Skill
generations used the local Claude critic agent (cross-family with the judge); baselines used
local Codex.

| Condition | composite | recall | API coverage | specificity | n |
| --- | ---: | ---: | ---: | ---: | ---: |
| `skill` | 0.72 | 1.00 | **0.33** | 1.00 | 3 |
| `baseline-zero-shot` | 0.84 | 1.00 | 0.61 | 1.00 | 3 |
| `baseline-few-shot` | 0.81 | 1.00 | 0.50 | 1.00 | 3 |

Tranche-C false-positive rate: **0.0 for all three** — no condition flagged the
`__return_true` public-read endpoint (the skill did not over-flag it either).

**Discrimination self-check: skill − zero-shot = −0.12** (threshold 0.20; **does not
discriminate**). Per `corpus-prereg.md` §6 / the answer-key prereg §6, a sub-threshold delta
means this slice **saturates** — a competent base model satisfies the `must_detect` list from
a short prompt — so the skill-vs-baseline composite comparison here is **not** a quality
verdict. Read the axes, not the ranking:

- **Recall is saturated (1.00 everywhere).** n=3, runs=1, and these three fixtures are caught
  by every condition. Detection does not discriminate at this scale; the corpus needs more
  fixtures (and harder ones) before recall separates conditions.
- **The only moving axis is API coverage, and it is deterministic (substring match, no
  judge).** The skill named fewer of the expected WordPress APIs (~1 of 3 per fixture) than
  either baseline. This is judge-independent and reproduces the API-naming deficit prior
  diagnostics flagged — the clearest actionable signal from this run.
- **Judge-family caveat:** the deterministic API axis is unaffected, but the judged recall
  axis pairs a same-family judge with the Codex baselines and a cross-family judge with the
  Claude skill; with recall saturated at 1.00 it does not bite here, but it must be controlled
  before a larger judged comparison.

**Honest bottom line:** on this slice the skill does not beat the baselines on composite, and
the gap is entirely lower exact-API naming, not worse detection or worse precision. That is
the localization recommendation 09 exists to produce. It is a 3-fixture directional read, not
a verdict. Reproduce and scale with:

```bash
python3 evals/harness/answer_key_score.py \
  --suite wordpress-security-critic \
  --run-id critic-pilot-<date> \
  --generate --judge gpt-5.5 --timeout-sec 900
# omit --fixtures to score the whole active corpus; drop --fast for runs=3
```

The scorecard (`scorecard.md` + `answerkey-summary.json`) carries per-condition
recall/API/specificity, the discrimination self-check, the tranche-C false-positive rate, and
tranche-J severity recall. Raw run: `evals/results/wordpress-security-critic/critic-pilot-fast-20260811/`.

## 5. Honest limitations (from `corpus-prereg.md` §6)

- **This corpus measures the critic; it does not improve it.** The first honest judged run may
  well confirm the skill trails a strong few-shot baseline — that localization is the point.
- **The few-shot baseline must be independently confirmed strong** or a skill win is a
  weak-baseline artifact. That human sanity check is still owed.
- **Tranche T can't fully exercise the critic until rec 01 lands** (the critic still can't run
  tools). T establishes the target and baseline now.
- **CVE-diff labels are noisier than WPCS's**; the `researcher` tranche is staged as drafts
  (`fixtures/_drafts/`) behind the human verification gate and is not yet populated.
- **This is an instrument, not a benchmark** — ~24 fixtures measure direction and localize
  weakness; scale via the CVE pipeline before any comparative claim.

## 6. Next

Recommendations 01 (critic Phase-0 evidence gate) and 02 (reproduction as price of admission)
become measurable against this baseline once the judged run above is recorded. Grow tranche J
via `build_cve_fixtures.py` + the human gate, and add the WPCS-invisible unbounded-query
patterns (`-1`, `nopaging`) as J fixtures.
