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

## 4. First three-condition judged run — status

The first `skill` / `baseline-zero-shot` / `baseline-few-shot` judged run was launched over a
security slice (`sec-idor-user-meta-v1`, `sec-public-read-return-true-clean-v1`,
`t-escapeoutput-xss-v1`). The **baseline lanes generate quickly; the `skill` lane is
compute-bound** in this environment — the critic-agent prompt is long and a single
low-effort Sonnet generation exceeded a 240s budget. A skill-lane generation *failure* would
show as recall 0 for `skill`, which is a generation artifact, **not** a skill-quality signal,
and must not be read as "skill trails baseline." The full judged pass should be run where the
Claude-agent CLI has a longer per-call budget:

```bash
python3 evals/harness/answer_key_score.py \
  --suite wordpress-security-critic \
  --run-id critic-pilot-<date> \
  --generate --fast --judge gpt-5.5 --timeout-sec 900
# omit --fixtures to score the whole active corpus; drop --fast for runs=3
```

The scorecard it writes (`scorecard.md` + `answerkey-summary.json`) carries per-condition
recall/API/specificity, the discrimination self-check, the tranche-C false-positive rate, and
tranche-J severity recall.

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
