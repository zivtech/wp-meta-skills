# Evidence Log — What We Tested, and What It Licensed Us To Say

Compiled 2026-08-28. Gated by `scripts/validate-evidence-log.py`.

## How to read this log

This is the record of what this project measured, including — especially — the
measurements that came back null. It is not a highlight reel with a modesty
section bolted on. Roughly half of what follows is a result that did not go our
way, and those rows are here for the same reason the positive ones are: they
were measured, and the measurement is what makes the rest of the numbers in this
repository worth anything.

If you are evaluating this work, three things are worth knowing before you read
the table:

**A null result is not a failure of the thing being tested.** "The skill prompt
showed no measurable review-quality edge over a strong few-shot baseline" means
exactly that, on that fixture set, with that scorer, at that sample size. It
does not mean the skill is worse, and several rows below say so explicitly. What
it does mean is that we stopped claiming an edge we could not demonstrate, which
is a different and more useful commitment than never having looked.

**The claim column is the load-bearing one.** Every row states what its result
does *and does not* license. Where a finding is quoted out of this document —
in an RFP response, by a prospect's technical advisor, in a room we are not in —
the claim column is the only thing travelling with it. It is written to survive
that trip without us there to add context.

**Provenance is stated per row, not assumed.** A finding whose analysis is
committed here but whose raw run archive is not is labelled that way. The
distinction is a required column, not a footnote, and the gate enforces it.

### Provenance vocabulary

| Value | Meaning |
|---|---|
| `analysis` | Path to the committed document in this repository that states the finding. Every row must have one. A finding with no committed analysis is **dropped from this log, not softened into prose.** |
| `archive: in-repo` | The raw run directory is committed here and can be re-read. |
| `archive: monorepo-internal` | The analysis is public; the raw run directory lives in the private `zivtech-meta-skills` monorepo and is **not** in this repository. The finding is *recorded*, not independently reproducible from this tree. |
| `re-run` | The harness that produced the finding, if it is in this repository. A finding can be re-runnable without its original archive being present — the experiment can be repeated, just not replayed. |

**The split is uncomfortable and is stated here rather than left to be
discovered.** Every one of the five positive rows has its raw archive bundled in
this repository. Not one of the eight null rows does. That is not a decision
anyone made on the record — it fell out of which runs were packaged for the
public release — but the shape it produces is a repository whose wins are
independently checkable and whose nulls have to be taken on our word. It is
tracked as open work in `v1-completion-todo.md` under "Publish or re-point the
evidence archives", and until it closes, the nulls below are the weaker half of
this log in exactly the way that most flatters us.

---

## Null and negative results

| # | What was tested | Measurement target | Result | What it licenses — and what it does not | Analysis | Archive | Re-run |
|---|---|---|---|---|---|---|---|
| N1 | Whether the `zivtech_prototype` prompt separates from a strong few-shot prompt under blind pairwise judging | Frontier-model per-task review quality | No certified separation. The prototype is top-tier but not distinguishable from a strong few-shot prompt. | Licenses: "our prompt is competitive with a strong baseline." Does **not** license any superiority claim, and does not license the inverse either — this is a null, not a demonstration that the skill is worse. | `docs/wordpress/skill-improvement-research-2026-06-20.md` | monorepo-internal | `evals/harness/run_pairwise_pilot.py` |
| N2 | Whether the skill improves detection or specificity on adversarial answer-key fixtures | Detection recall and finding specificity | No measurable edge, plus a small API-naming deficit. | Licenses: the decision to close the review-quality arc and pivot to exact API naming, which is what the Exact API contract exists to fix. Does **not** license a claim that the skill degrades review quality. | `docs/wordpress/skill-improvement-research-2026-06-20.md` | monorepo-internal | `evals/harness/answer_key_score.py` |
| N3 | Absolute-score candidate discrimination across four conditions and four fixtures | Normalized separation between known-strong and known-weak conditions | Failed. `-0.113` observed against a required `0.2`; scoring saturated at 99.5–100 for three of four conditions. | Licenses: abandoning absolute single-judge scoring for this comparison, and the switch to blind pairwise. Does **not** license any conclusion about the conditions themselves — a saturated instrument measures nothing about what it was pointed at. | `evals/suites/wordpress-skill-candidate-eval/pilot-results.md` | monorepo-internal | `evals/harness/run_wordpress_candidate_pilot.py` |
| N4 | Whether the skill lifts a cheaper model (Haiku) toward frontier baseline quality | Cheaper-model lift on adversarial answer-key fixtures | Directional null. `zivtech - zero-shot = -0.006`, `zivtech - few-shot = 0.039`; both confidence intervals straddle zero. | Licenses: not back-projecting a cheap-model value claim. Does **not** license a universal cheaper-model theorem — this was one fast run, and the boundary is stated in the source. | `docs/wordpress/v1-completion-todo.md` | monorepo-internal | `evals/harness/answer_key_score.py` |
| N5 | Whether the skill's exact-API coverage edge over a few-shot baseline is real | API-naming coverage (deterministic substring recall, no judge, n=32) | Confounded. The headline `+0.128` edge (0.777 vs 0.649) survives only because the skill writes **2.24×** more text; coverage is recall, which length inflates. 13 of 17 apparent wins reverse under density normalization. Two genuine length-independent wins remain. | Licenses: closing the coverage axis as internal-historical, and the pivot to oracle-backed gate-pass measurement. Does **not** license the `+0.128` number in any external context — quoting the headline without the density correction misrepresents this result. | `docs/wordpress/api-naming-coverage-closeout-2026-06-22.md` | monorepo-internal | `evals/harness/answer_key_score.py` |
| N6 | Whether machine-optimizing the persona against the deterministic gate beats a hand-written seed | Held-out gate-pass after GEPA optimization | No held-out gain (Δ = 0.0). The optimization loop worked — it improved the training fixture with no human reading the oracle — but no candidate beat the seed on held-out, and one regressed. | Licenses: the conclusion that the **repair loop, not the persona, is the lever** — including when the persona is machine-optimized rather than hand-written. Does **not** license a claim that prompt optimization never works; this is n=1 fixture on one holdout. | `docs/wordpress/gepa-executor-spike-2026-06-22.md` | monorepo-internal | `evals/harness/run_gepa_executor_optimization.py` |
| N7 | Whether the skill persona beats a stronger frontier baseline on deterministic executor gates | Gate-pass on the hardest modern-surface fixture (`abilities-ai-surface-v1`) | Equivalent. `sonnet` + skill and `gpt-5.5` baseline follow an identical trajectory: both substantively correct zero-shot, both failing only on distribution-metadata nits, both fully green in one repair iteration. | Licenses: "the executable gate plus repair loop is the model-agnostic lever, and a cheaper model reaches the same gate outcome." Does **not** license a superiority claim in either direction — it is a tie, on one fixture, single-shot. | `docs/wordpress/executor-gate-pass-experiment-2026-06-22.md` | monorepo-internal | `evals/harness/run_executor_repair_loop.py` |
| N8 | The 27-fixture candidate superiority benchmark | Frontier-model review-quality superiority | Never run. Recorded as blocked and deliberately kept blocked. | Licenses: nothing about the suite's quality — that is the point. It is listed because a benchmark designed, costed, and then **not** run for lack of a defensible measurement target is evidence about how this project operates. Does **not** license the inverse reading either: the benchmark was not abandoned because we expected to lose it, and its absence is not a result. Reopening it requires a changed target, not a bigger budget. | `docs/wordpress/v1-completion-todo.md` | monorepo-internal | not applicable — never executed |

---

## Positive deterministic proofs

Same instruments, same discipline, results that did go our way. They are in the
same document deliberately: a log that collected only nulls would be as
misleading as one that collected only wins, and the reader needs both to judge
whether the measurement culture is real.

| # | What was proven | How it was proven | What it licenses — and what it does not | Analysis | Archive |
|---|---|---|---|---|---|
| P1 | A generated block's Interactivity API behavior actually works in a real browser | Playwright clicked the built block's button in WordPress `7.0` and asserted `context.count` moved `0` → `1`, with no page or console errors, after passing block build, static certification, WPCS/PHPCS, Plugin Check, editor insertion, and frontend render | Licenses: "generated Interactivity blocks are verified by execution, not by inspection." Does **not** license claims about long-run variance or broad Interactivity coverage — this is one generated block. | `docs/wordpress/v1-completion-todo.md` | `evidence/wordpress-skill-candidate-eval/generated-block-interactivity-full-profile-20260621/scorecard.md` |
| P2 | A generated block survives WordPress' deprecation path | One legacy serialized fixture migrated through the deprecation path into current saved markup and correct frontend output | Licenses: "we can prove a saved-content migration rather than assert it." Does **not** license a claim about arbitrary third-party legacy markup. | `docs/wordpress/v1-completion-todo.md` | `evidence/wordpress-skill-candidate-eval/generated-block-deprecation-full-profile-20260621/scorecard.md` |
| P3 | A generated plugin's ability is discoverable and executable through the WordPress MCP Adapter | Installed the adapter, listed the default server, called `tools/list` through `wp mcp-adapter serve`, discovered the generated MCP-public ability, and executed it via `mcp-adapter-execute-ability` — plus WPCS/PHPCS and Plugin Check | Licenses: "the modern agent surface is proven end-to-end for generated code." Does **not** license claims about adapter stability — the adapter emitted upstream PHP deprecation notices, recorded as adapter/runtime risk rather than generated-plugin failure. | `docs/wordpress/v1-completion-todo.md` | `evidence/wordpress-skill-candidate-eval/generated-mcp-adapter-full-profile-20260621/scorecard.md` |
| P4 | A generated AI Client provider registers and answers a real prompt call | Activated a deterministic no-auth provider in WordPress `7.0`, verified `wp_ai_client_prompt()` and the default registry, confirmed provider and connector registration, invoked the generated helper, and matched exact expected output | Licenses: "the AI Client provider boundary is proven for a deterministic provider." Does **not** license any claim about credentialed third-party provider behavior, which remains explicit negative space. | `docs/wordpress/v1-completion-todo.md` | `evidence/wordpress-skill-candidate-eval/generated-ai-client-provider-full-profile-20260621/scorecard.md` |
| P5 | A local open-weights model (llama-70b) converges to a clean artifact through the repair loop | Iterative repair against persisted PHPCS diagnostics and WPCS repair hints, reaching zero errors on every macOS-reachable gate, then handed to the no-secrets Linux CI lane for the gates a laptop cannot run | Licenses: "the deterministic feedback loop carries a local model to a clean artifact." Does **not** license a full-profile pass claim — the Linux-only gates are handed off precisely because they were not run locally. | `docs/wordpress/repair-loop-levers-reland-2026-08-24.md` | `evals/results/llama70b-abilities-green7-20260825/` |

---

## What this log does not cover

Stated with the same specificity as the claims, because a boundary that is vague
is not a boundary.

- **No external comparison is licensed by anything here.** No row supports a
  claim that this suite outperforms upstream WordPress skills, a baseline
  prompt, or another vendor's tooling. The rows that tested exactly that (N1,
  N2, N5) came back null, and the benchmark designed to settle it (N8) was not
  run.
- **Sample sizes are small and stated per row.** Several findings are n=1
  fixture. They are recorded as directional evidence, not as effects.
- **The judge was internal and uncalibrated** wherever a judge was used at all.
  The deterministic gates (N7, P1–P5) do not use a judge, which is why they
  carry more weight here than the judged rows.
- **Nothing here measures delivery outcomes.** No row connects to client
  satisfaction, project velocity, defect rates in production, or cost. Those are
  the questions a buyer actually has, and this log does not answer them.
- **No null result's raw archive is in this repository.** All eight null rows
  are `monorepo-internal`: you are reading our analysis of our data, not our
  data. All five positive rows bundle their archive. Read the nulls accordingly
  — they are the rows you cannot currently check for yourself.

## Related

- `docs/wordpress/v1-completion-todo.md` — open work, including publishing or
  re-pointing the archives named above.
- `docs/wordpress/skill-improvement-research-2026-06-20.md` and
  `docs/wordpress/skill-improvement-research-2026-06-22.md` — the syntheses that
  several rows summarize.
- `docs/wordpress/runtime-oracle-runbook.md` — evidence semantics for the
  deterministic gates, including why absence of a failure is not a pass.
- Root `EVIDENCE.md` — the surface index this log is reachable from.
