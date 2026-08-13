# Independent Baseline Strength Review

**Status:** open — awaiting a reviewer who did not author the fixtures or the baselines.
**Prepared:** 2026-08-13. **Blocks:** the full 24-fixture judged run, and therefore recs 01/02.
**Estimated time:** 30–45 minutes. Four prompts, ~50 lines each.

---

## 1. What you are deciding

`corpus-prereg.md` §6 makes this a hard prerequisite:

> **The few-shot baseline must be independently confirmed strong** or a skill win is a
> weak-baseline artifact. That human sanity check is still owed.

Everything comparative in the critic corpus rests on it. If `baseline-few-shot` is a
strawman, any skill advantage is manufactured and the corpus quietly launders a weak
opponent into a quality claim. The corpus is explicitly an instrument, not a benchmark —
but an instrument calibrated against a strawman is not an instrument.

You are the control on that. Nobody who wrote the fixtures can perform this check, which
is why it has stayed open.

## 2. The standard

A baseline is **strong** when a competent WordPress reviewer, handed that prompt and
nothing else, would produce roughly what a good human reviewer produces. Concretely, per
the prereg, each `baseline-few-shot.md` should:

1. **Name the review dimensions explicitly** — not "review the code", but the actual axes.
2. **Carry worked findings** with `file:line`, why it is reachable, and a concrete fix.
3. **Carry a calibration non-finding** — correct code that looks suspicious, marked correct,
   so the prompt teaches restraint and not just suspicion.
4. **Bound its claims** — no runtime/production proof from static review.

The operative test is adversarial, not aesthetic:

> **Could you make this prompt meaningfully stronger without telling it about specific
> fixtures?** If yes, it is not yet strong, and you should say what you would add.

## 3. Read this before you start: the API axis is contaminated

While assembling this package I measured something that changes what you are adjudicating.

`answer_key_score.py` scores **API coverage** as a deterministic substring match of each
fixture's `expected_wordpress_apis` against the candidate's response. I scored the baseline
prompts *themselves* as if they were responses, using the scorer's own matcher:

| Condition | Mean API coverage of the answer key, before reading any fixture | Fixtures ≥ 0.50 |
| --- | ---: | ---: |
| `baseline-few-shot` | **0.79** | 20 / 22 |
| `baseline-zero-shot` | 0.00 | 0 / 22 |

Seven fixtures score **1.00** — the prompt names *every* API the scorer expects. Reproduce:

```bash
python3 evals/harness/measure_baseline_api_leakage.py
```

The few-shot prompt names `esc_like`, `update_meta_cache`, `viewScriptModule`,
`wp_load_alloptions`, `check_admin_referer`, `templateParts`, and most of the rest, because
naming remediation APIs is what a good review prompt does. **This is not misconduct and the
prompts were not written to game anything.** It is a construct-validity problem: an axis
meant to ask *"did the reviewer know the right WordPress surface for this defect?"* cannot
ask that of a condition whose prompt supplied the surface.

Why it matters for the pending run: the pilot's headline was that the skill named **fewer**
exact APIs (0.33) than the baselines (0.50–0.61), called "the clearest actionable signal"
and "judge-independent". It is judge-independent. It is not **prompt**-independent. A large
part of that gap may be the few-shot prompt's own vocabulary echoing into its outputs, not a
skill deficit. Nobody has separated those yet.

The same pattern extends past the API axis: the dimension lists describe, in order, most of
the tranche-J defects the corpus tests — object-capability vs meta-cap, discarded
`wp_verify_nonce` return, `LIKE` without `esc_like`, decorative capability branch, N+1
without priming, uncached remote on the request path, `viewScript` vs `viewScriptModule`,
template-part area mismatch. Tranche J is meant to measure judgment on defects tools cannot
see. A prompt enumerating those defects is answering from a list rather than exercising
judgment. **Quantifying that is not in this package** — it needs your read.

## 4. What to read

| Suite | Prompt | Corpus fixtures |
| --- | --- | ---: |
| `wordpress-critic` | [`baselines/baseline-few-shot.md`](../wordpress-critic/baselines/baseline-few-shot.md) | 2 |
| `wordpress-security-critic` | [`baselines/baseline-few-shot.md`](../wordpress-security-critic/baselines/baseline-few-shot.md) | 13 |
| `wordpress-performance-critic` | [`baselines/baseline-few-shot.md`](../wordpress-performance-critic/baselines/baseline-few-shot.md) | 7 |
| `wordpress-theme-critic` | [`baselines/baseline-few-shot.md`](../wordpress-theme-critic/baselines/baseline-few-shot.md) | 2 |

Each suite's `baseline-zero-shot.md` is a single line by design — the deliberately weak
pole. It needs no review; it is not meant to be strong.

For context on what the fixtures test, `corpus-prereg.md` §3 describes the three tranches.
**Do not read the fixtures themselves before judging prompt strength** — knowing the answers
makes it very hard to assess whether a prompt would find them.

## 5. The questions

**Per baseline (four times):**

- **Q1 — Strong-faith opponent?** Handed this prompt and nothing else, would a competent
  WordPress reviewer produce roughly what you would? Yes / No.
- **Q2 — What would you add?** Name at least one concrete improvement, without referring to
  any specific fixture. If you genuinely cannot, say so — that is the strongest evidence the
  prompt is already strong.
- **Q3 — Strawman tells?** Anything that reads as deliberately hobbled: a missing obvious
  dimension, a misleading example, advice that would cause false positives.

**Across all four:**

- **Q4 — The API axis.** Given §3, is API coverage salvageable as a comparative axis? Options
  worth considering, not exhaustive: report it descriptively but exclude it from composite;
  hold both conditions' prompt vocabulary constant; replace it with a measure of whether the
  named API is *correct for the defect* rather than merely present; drop the axis.
- **Q5 — Tranche J.** Do the dimension lists give away enough of the J defects that J stops
  measuring judgment for the few-shot condition? If so, what is the fix — generalize the
  dimensions, or accept it and reinterpret what J measures?

## 6. Not being asked

To keep this bounded and to keep your read independent:

- **Not** reviewing the skill prompts, or whether the skill is good.
- **Not** reviewing fixture correctness — a separate gate
  (`verify_critic_tool_invisibility.py`) already enforces tranche-J tool-invisibility.
- **Not** reviewing the scoring math, the judge panel, or the judge-family control.
- **Not** approving any comparative claim. No judged run exists to approve.

## 7. Verdict

Fill in, commit, and this gate closes.

```text
Reviewer:
Date:
Relationship to the corpus (must not be fixture or baseline author):

wordpress-critic               Q1: strong / not strong    Q2: ______    Q3: ______
wordpress-security-critic      Q1: strong / not strong    Q2: ______    Q3: ______
wordpress-performance-critic   Q1: strong / not strong    Q2: ______    Q3: ______
wordpress-theme-critic         Q1: strong / not strong    Q2: ______    Q3: ______

Q4 API axis:
Q5 Tranche J:

VERDICT: [ ] all four strong -- the judged run may proceed
         [ ] strong with the changes named above, to be made first
         [ ] not strong -- rewrite before any comparative run
```

Record the outcome here and in `corpus-prereg.md` §6. A **not strong** verdict is a useful
result, not a failure: it is cheaper to find now than after a judged run has been read as
evidence.
