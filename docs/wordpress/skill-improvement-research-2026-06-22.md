# WordPress Skill Improvement — Method-Frontier Research (2026-06-22)

## Bottom Line

The four converging negative results (pairwise, fast answer-key, adversarial answer-key, and the 2026-06-22 gate-pass experiment) established that the **prompt-only skill class is at its ceiling** for this task: hand-authored personas do not beat a strong baseline, and the only lever that ever moved an outcome was the deterministic-oracle + repair loop. This note surveys the **untried** method space — the methods outside that class — given the one keystone asset the repo already owns: a **deterministic, verifiable gate**.

Six candidate families, ranked by lift-to-payoff *for this repo specifically*. The headline: the cheapest high-value move is **GEPA prompt/program optimization run against the gate we already built** — the method cited as "blocked on a good metric" in the 2026-06-20 notes, after which we built the metric and never pointed the optimizer at it. The single cross-cutting risk — **reward hacking on our own gate** — is verified and forward-looking: it bites the methods recommended here, not the current loop.

Consistent with the repo evaluation boundary: **this is not a superiority claim.** Every result below is from an adjacent domain (Python / SWE-bench / math). Transfer to PHP/WordPress is unproven and is treated as negative space, not assumption.

## Provenance & method (read this before trusting the numbers)

Source material came from a deep-research workflow (5 search angles, 19 sources fetched, 93 claims extracted). A server-side rate-limit throttle killed the workflow's verification and synthesis tail: of the 20 claims it reported "killed," **18 were `0-0 (3 abstain)` — all three verifier votes failed on the throttle, not on the merits.** Only one claim drew an actual refute vote.

This session finished the tail by hand: the four claims the recommendations hang on were re-verified by direct source fetch (2026-06-22). Verification status is tracked per row in the ledger and must be respected — **do not treat ⚠︎ rows as established.**

## Verification ledger

| Method | Source | Status (2026-06-22) |
|---|---|---|
| **GEPA** — optimize prompts/programs against an existing metric | `github.com/gepa-ai/gepa` | ✅ verified this session — figures confirmed, stronger than the extracted claim |
| **DAG** — retrieve API docs at generation time for rare APIs | arXiv 2407.09726 | ✅ verified this session — **plus a caveat that reframes the method** |
| **Reward hacking on gates** | arXiv 2603.07084 (*Countdown-Code*, Khalifa et al., Mar 2026) | ✅ verified this session — real paper; future-dated arXiv ID was legitimate |
| **SWE-agent ACI / linter-in-loop** | arXiv 2405.15793 | ✅ paper + 12.5% pass@1 verified; specific ablation figures are from the paper body |
| On-policy distillation | `thinkingmachines.ai/blog/on-policy-distillation` | ✓ workflow-confirmed 3-0 |
| REDI — train on *failed* traces too | arXiv 2505.24850 | ✓ workflow-confirmed 3-0 (mechanism); cheaper-model-lift sub-claim drew 1 refute |
| RFT small-data lift | `cookbook.openai.com` RFT example | ⚠︎ unverified (throttle) — reputable primary source |
| S\* test-time scaling | arXiv 2502.14382 | ⚠︎ unverified (throttle) |
| SWE-Synth synthetic fixtures + hybrid verifier | arXiv 2504.07164 | ⚠︎ unverified (throttle) |

## The untried method space, ranked for this repo

### Tier 1 — no training, runs on assets already owned

**1. GEPA — machine-optimize the artifact against the gate. (Already half-built; never run.)**
The 2026-06-20 notes cited GEPA as "relevant only if the metric reflects the desired improvement," then built exactly that metric and never closed the loop. Verified preconditions (all owned): a seed candidate; an evaluator returning a numerical score (`certify_wordpress_executor_artifact.py`); **textual execution feedback** — GEPA's "actionable side information," which the repo already emits as machine-readable WPCS/Plugin-Check failures and `repair-prompt.md`; and a reflection LLM. **No weight updates. ~35× fewer evaluations than RL (100–500 vs 5,000–25,000+ for GRPO).** Verified gains in code-shaped tasks: **55% → 82%** resolve rate on a Jinja coding agent; **67% → 93%** on MATH via DSPy full-program optimization; 32% → 89% on ARC-AGI; 46.6% → 56.6% (GPT-4.1 Mini, AIME 2025).

Why #1 here: it is a *direct, defensible test of the central negative result.* We proved hand-authored personas don't beat baseline; GEPA asks the unasked follow-up — does a *machine-optimized* artifact against our oracle? **Either answer is internally publishable:** a win breaks the saturation; a loss is the cleanest possible proof that the prompt class is exhausted and effort should move to tools/training. Lift: low (a harness, not a GPU).

**2. DAG — retrieve the exact API surface, *selectively*. (Targets the one measured weakness.)**
The only non-confounded deficit is exact API naming, which we tried to patch with a prompt *contract* (assert the names). DAG does the principled version: retrieve real signatures into context at generation time. Verified: **+8.20% absolute** on rare-API correctness for GPT-4o on CloudAPIBench (low-frequency APIs 38.58% → 47.94%).

The verified caveat *is* the design spec: **DAG helps only low-frequency APIs and *hurts* high-frequency ones — a −39.02% absolute drop — when retrieval is indiscriminate with a sub-optimal retriever.** This maps onto our problem precisely. The APIs models get wrong are the rare, post-cutoff ones — **Abilities API, MCP Adapter, AI Client, Connectors (WP 6.9–7.0)**; nobody hallucinates `register_post_type`. Build a retrieval tool over the WP developer handbook + core source, **frequency-gated** so it fires on `wp_register_ability` and stays silent on everyday calls. Serves both win conditions: correct new-surface code (adoption) and a measurable API-naming-accuracy benchmark with/without retrieval (defensibility). Lift: low-moderate.

**3. Verifiers-as-tools — ship the repair loop as an MCP, not a prompt.**
The repo's own SWE-agent citation is the evidence: exposing lint/test/build as *interactive agent tools* beats a static reminder (12.5% pass@1 vs a 3.8% RAG baseline), and the highest-impact ACI feature reported is **a linter wired into the edit tool that rejects broken edits and feeds the error back** — i.e., our repair loop. Today that loop is the eval harness, run by us; a developer's own agent session cannot call it. Wrap `certify_wordpress_executor_artifact.py` + `run_wordpress_runtime_smoke.py` as an **MCP server** (WPCS / Plugin Check / wp-env / PHPUnit as callable tools). Most direct path to real WP-dev adoption: it converts internal eval infra into the product. Lift: low — the scripts exist. (See guardrail before letting the agent author the tests it is scored on.)

### Tier 2 — bigger levers, more to build

**4. Test-time scaling against the verifier (S\*).** The current loop is single-shot + *sequential* repair. S\* adds *parallel* best-of-N and **synthesizes distinguishing test inputs** to select among candidates that all pass. Reported (⚠︎ unverified): a 3B model + scaling beats GPT-4o-mini; GPT-4o-mini + S\* beats o1-preview by 3.7% on LiveCodeBench. Cheaper-model lift *without training* — orchestration around the gate already owned. Lift: moderate.

**5. Learn from the trajectories (on-policy distillation / REDI / RFT).** The biggest lever and the highest *organizational* friction — this repo is a skills/consulting practice, not an ML-training shop, so treat this as a strategic fork, not a quick win. Verified: on-policy distillation is 7–10× faster / 50–100× cheaper than RL and carried a small model 60% → 70% on AIME in ~150 steps; **REDI trains on gate-*failing* trajectories too** (fully offline, needs only the verifiable label — signal currently discarded). Constraint (RFT, ⚠︎ unverified): the base model must already succeed *sometimes* (~0.6 baseline) — training cannot bootstrap an absent capability. This tier is where a genuinely non-confounded benchmark win is most plausible (moving weights, not prompts, escapes the saturation that closed all four prompt-only evals), but it is a different muscle and is gated on Tier 0.

### Tier 0 — the enabler that unblocks the rest

**6. Escape N=1 fixture starvation (SWE-Synth / SYNGEN-style synthesis + mining).** Every method above is throttled by the single hard fixture — the repo's own negative space says so. Reported (⚠︎ unverified): synthesize executable tasks from commits (>8.7K demonstrated), and a **hybrid verifier (execution + execution-free LLM) beats either alone (42–43% → 51%)** on SWE-bench Verified. For this repo: mine real WP plugin/theme repos and the existing Abilities/MCP example packets into many gate-checkable fixtures. Without this, GEPA optimizes against one signal, test-time scaling isn't measurable, and the training tier has no corpus. Do it alongside #1.

## Cross-cutting guardrail: reward hacking on our own gate

The *Countdown-Code* paper (verified real, Khalifa et al., Mar 2026) is aimed straight at this architecture:
- **1% reward-hack contamination in distillation SFT data resurfaces and *amplifies* under subsequent RL.** → applies to Tier-2 #5.
- **An agent with write access to *both* the solution and the test/verifier code drives proxy-reward to 1 while true-reward is 0.** → applies to Tier-1 #3 the moment an MCP lets the agent author the tests it is graded on.

The *current* repair loop is safe — the gate is the harness, read-only to the generator. The risk is forward-looking, in exactly what is recommended here. Design rules:
1. **Keep the scoring oracle read-only to the agent.** Let it *call* WPCS/Plugin Check, never *edit* the ruleset or the graded tests.
2. **Hold out fixtures** the optimizer/trainer never sees.
3. Honor the repo's own note — **"gate = shippability, not deep behavior."** GEPA (or any optimizer) maximizing gate-pass can yield a plugin that is WPCS-clean and activates but behaves wrong. That blind spot is the ceiling on every optimize-toward-the-gate method here; closing it requires behavior-level oracles, not just shippability gates.

## Recommended first step

**GEPA against the existing gate + a first batch of mined fixtures (#1 + #6 together).** Lowest lift, reuses everything built, the reward-hacking guardrail is cheap at prompt-optimization scale, and it answers the stuck question directly: *is the prompt class actually exhausted, or merely un-optimized?* DAG-for-rare-APIs (#2) is the close second because it is the only method targeting the one proven weakness.

Concrete spike (to be built in a fresh session): wire GEPA with `certify_wordpress_executor_artifact.py` as the evaluator, `repair-prompt.md` output as the textual feedback channel, and the Abilities/MCP example packets as the seed + initial fixture set; hold out at least one fixture for honest scoring.

## Negative space — what this does NOT claim

- **No transfer guarantee.** All evidence is Python / SWE-bench / math. DAG transfers most cleanly (rare-API correctness is domain-general; WP's new surfaces are textbook rare APIs). GEPA transfers in *mechanism* (metric-agnostic) even if magnitude won't. Tier-2 training numbers (AIME/SWE-bench) are least likely to survive the move to WordPress — do not budget against them.
- **⚠︎ rows are unverified** (RFT, S\*, SWE-Synth) — primary sources, but not re-confirmed after the throttle. Verify before betting work.
- **No claim that any method beats baseline on WordPress.** The claim is narrower: these are untried, evidence-backed in adjacent domains, and compatible with the verifiable asset already owned.
- **The training tier is a business-model fork**, not just a technical one. Flagged, not recommended by default.

## Sources consulted (with verification status)

- GEPA framework — https://github.com/gepa-ai/gepa — ✅ verified 2026-06-22
- On Mitigating Code LLM Hallucinations with API Documentation (DAG / CloudAPIBench) — https://arxiv.org/abs/2407.09726 — ✅ verified 2026-06-22
- Countdown-Code: Reward Hacking in RLVR (Khalifa, Khan, Tafveez, Peng, Wang, Mar 2026) — https://arxiv.org/abs/2603.07084 — ✅ verified 2026-06-22
- SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering — https://arxiv.org/abs/2405.15793 — ✅ paper verified 2026-06-22; ablation figures from body
- On-Policy Distillation (Thinking Machines) — https://thinkingmachines.ai/blog/on-policy-distillation/ — ✓ workflow 3-0
- REDI: learning from positive and negative reasoning traces — https://arxiv.org/html/2505.24850v2 — ✓ workflow 3-0 (mechanism)
- Reinforcement Fine-Tuning example (OpenAI Cookbook) — https://cookbook.openai.com/examples/reinforcement_fine_tuning — ⚠︎ unverified
- S\*: Test-Time Scaling for Code Generation — https://arxiv.org/abs/2502.14382 — ⚠︎ unverified
- SWE-Synth / procedural executable environments + hybrid verifier — https://arxiv.org/abs/2504.07164 — ⚠︎ unverified

## Continuity

Builds on `skill-improvement-research-2026-06-20.md` (the four-negatives synthesis and the repair-loop result) and `executor-gate-pass-experiment-2026-06-22.md` (skill ≈ baseline on deterministic gate-pass; repair loop as the model-agnostic lever). This note answers the next question those two raise: *given the gate works and the prompt class is saturated, what untried method uses the gate?*
