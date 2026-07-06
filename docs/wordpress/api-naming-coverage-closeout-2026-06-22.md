# API-Naming Coverage Axis — Close-Out and Gate-Pass Pivot (2026-06-22)

## Bottom Line

The exact-WordPress-API **coverage** axis is closed as confounded and internal-historical. It does not support a skill-over-baseline claim. This note records the closing evidence and the pivot to oracle-backed executor gate-pass measurement. It does not rewrite the 2026-06-20 synthesis (historical evidence stands).

## What ran

- Suite: `evals/results/wordpress-skill-candidate-eval/api-naming-skill-vs-fewshot-20260622/`
- n=32 fixtures, both conditions on **Sonnet**, scorer `answer_key_score.api_coverage` (deterministic, normalized substring against each rubric's `domain_signals.expected_wordpress_apis`). No judge.
- Generation completed via a guarded in-process workflow (27 remaining outputs, 0 failures); 64/64 outputs whole, no stubs.

## Result and the confound

- Headline: skill mean coverage **0.777** vs few-shot baseline **0.649** (+0.128; 17 W / 5 L / 10 T).
- **Verbosity confound:** skill writes **2.24×** more text (19,321 vs 8,642 chars). `api_coverage` is recall, which length inflates.
- Length control added to `score_api_naming.py` — matched expected APIs per 1k chars ("density"):
  - Baseline is **1.80× more API-dense** (0.434 vs 0.241); density delta is **negative on 28/32** fixtures.
  - **13 of 17 skill "wins" reverse** under density (`length_confounded_wins`).
  - Only **2 genuine length-independent skill wins** — fixtures where the baseline scored literal 0.000: `block-deprecation-silent-break`, `triage-routing-risk`.
- Persisted fields in `api-naming-summary.json`: `verbosity_ratio`, `skill_mean_density_per_1k`, `baseline_mean_density_per_1k`, `density_ratio`, `length_confounded_wins`.

## Why this axis is historical, not live

1. **Confounded metric.** The coverage edge is mostly output length, not naming quality.
2. **Wrong comparator.** This run is Sonnet-vs-Sonnet. Per the 2026-06-20 synthesis (Design Implication #4), the prospective baseline is newest-ChatGPT-level (`gpt-5.5` via isolated Codex), not Sonnet.

Both align with 2026-06-20 Design Implication #1: more runs at the same target resample a saturated/confounded measurement.

## Negative space (what this does NOT claim)

- Not a claim that the skill is *worse* at API naming — 2 real wins and a density gap are not enough to invert it.
- Not a claim that coverage/recall is meaningless — only that it is length-sensitive and was read without controlling for length.
- Precision (naming *wrong/irrelevant* APIs) remains **unmeasured deterministically**. `domain_signals.must_not_penalize_or_do` is natural-language conclusions needing an LLM judge. The principled successor for the API axis is the prompt-contract validator `scripts/validate-wordpress-exact-api-contract.py`, which blocks generic `expected_wordpress_apis` labels.

## Pivot (decided 2026-06-22)

Aim the next run at the lane that survives measurement: **oracle-backed executor gate-pass**.

- Conditions: `baseline-gpt-5.5` (isolated Codex) vs skill (+ deterministic repair loop).
- Target: **hard modern-surface** executor fixtures (Abilities API, MCP adapter, AI Client/Connectors) — easy fixtures saturate even against gpt-5.5 (2026-06-20 bottom line).
- Metric: deterministic gates (packet → materialize → static cert incl. `php_wpcs_shape_heuristics` → php-lint → WPCS/PHPCS → Plugin Check → `wp-env` runtime → behavior assertion), reported as **pass@1, pass@k-with-repair, per-gate failure breakdown, and variance across N runs**. Binary gate-pass on a real WordPress install is un-confoundable.
