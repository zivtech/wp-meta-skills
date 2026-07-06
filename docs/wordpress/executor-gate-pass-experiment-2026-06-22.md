# Executor Gate-Pass Experiment — Skill vs gpt-5.5 Baseline (2026-06-22)

## Bottom Line

On the hardest available modern-surface executor fixture (`abilities-ai-surface-v1`, WP 6.9/7.0 Abilities API), the cheaper **sonnet + skill-persona** and the stronger **gpt-5.5 baseline** are **equivalent on deterministic gate-pass** — identical trajectory, no measurable edge either way. Both produce substantively-correct plugins zero-shot and both fail the release gate only on trivial distribution metadata; both reach a fully clean gate in **one** deterministic-feedback repair iteration. The decisive, model-agnostic lever is the **executable gate + repair loop**, not the persona or the model. Internal-only; not a superiority claim (consistent with the 2026-06-20 synthesis: skill ≈ strong baseline).

## Question

The prose-quality and answer-key axes are saturated/confounded. This run tests the one lane that cannot saturate: does the skill apparatus let a model produce an artifact that **passes real deterministic WordPress gates** (WPCS + Plugin Check + wp-env activation) where a strong baseline cannot — on a hard modern surface?

## Design

- **Fixture:** `wordpress-plugin-executor/fixtures/abilities-ai-surface-v1.md` (the only hard modern *fixture*; mcp-adapter/ai-client exist only as example packets, not fixtures).
- **Arms (single-shot, fair):**
  - `baseline` = gpt-5.5 via isolated `codex exec` (medium effort), prompt = `baselines/baseline-zero-shot.md` + fixture.
  - `skill` = sonnet via the `wordpress-plugin-executor` persona, prompt = persona + fixture. Tool-less, no answer hints.
- **Gate (11-gate runtime profile):** `certify_wordpress_executor_artifact.py --profile static` (packet contract → materialize → static heuristics) → `run_wordpress_runtime_smoke.py --provision-full-profile --strict-full-profile` (php-lint, WPCS/PHPCS via local `vendor/bin/phpcs`, Plugin Check inside wp-env, WP 7.0 activation). Deterministic, artifact-agnostic.

## Results

| Stage | Baseline (gpt-5.5, 13.7KB) | Skill (sonnet+persona, 19.2KB) |
|---|---|---|
| **Zero-shot** | 10/11 — fail `plugin_check` only | 10/11 — fail `plugin_check` only |
| **Failing detail** | `plugin_header_no_license`, `missing_readme_header_tested` | `plugin_header_invalid_plugin_uri_domain` (example.com), Domain Path warning |
| **After 1 repair iteration** | **11/11 — "No errors found"** | **11/11 — "No errors found"** |

Both pass *every substantive gate* zero-shot: packet contract, php-lint, **WPCS**, all security heuristics, all **AI-surface (Abilities/MCP/AI-Client) heuristics**, and **activation in WP 7.0**. The only zero-shot failures are distribution-metadata header nits (different ones per arm). The skill persona included License + readme headers the baseline omitted, but used a placeholder `example.com` URI; net — no quality gap.

## The lever: repair loop

Feeding each arm's exact `plugin_check` errors back as a single repair instruction → regenerate → re-gate took **both** arms from fail → fully green in **one** iteration. The repair loop is model-agnostic and is the only mechanism in this run that changed an outcome. This is the first end-to-end fail→green demonstration in `wp-meta-skills` itself (the bundled golden example packet does **not** pass the strict gate — see findings).

## Conclusion & recommendation

- **No skill/model edge on gate-pass.** Cheaper sonnet+skill ties stronger gpt-5.5. Persona-prose tuning is not the lever (4th converging negative result).
- **Automate the repair loop inside the executor sub-agents.** It is currently a *manual* handoff (`repair-prompt.md`). A `certify → if fail, feed repair-prompt back → regenerate → re-certify (≤k)` loop is the concrete, evidence-backed improvement, and it lifts any model. This is the real answer to "help LLMs assist in specialized sub-agents": wire them to deterministic oracles with automated feedback, not better prompts.

## Harness findings (actionable, beyond the headline)

1. **`invoke.py --mode executor` mangles the certified output.** The multi-stage pipeline's stage-2 "reproduction" degrades both lanes: baseline stage2 reformats to a non-contract artifact dump (`Generated artifact:`); skill stage2 tool-complains because the executor persona assumes tools but the harness runs `--tools ""`. The canonical `<fixture>.md` (stage2 copy) is unreliable. Use single-shot, or fix the reproduction stage.
2. **The golden example packet is not gate-clean.** `examples/abilities-ai-surface-v1.materializable-packet.md` fails strict runtime on `phpcs_wpcs` + `plugin_check` (missing GPL `License:` header). Repair it or mark it static-only.
3. **Nested `claude -p` hangs / is very slow in this environment.** codex and the in-session Agent tool work reliably; the nested Claude CLI did not.

## Follow-up: automated repair loop (implemented 2026-06-22)

The manual repair handoff is now a standing capability: `evals/harness/run_executor_repair_loop.py`.
- Pure `orchestrate(generate_fn, certify_fn, max_repairs)` core (injectable, mirroring `run_pairwise_pilot.py`), unit-tested in `evals/harness/tests/test_executor_repair_loop.py` (9/9 pass).
- `main()` wires single-shot generation (`invoke.py`: claude for skill lanes, codex for `baseline-*`) and the deterministic gate (certifier static + provisioned runtime smoke), feeds the machine-readable Plugin Check / WPCS failures back, and records pass@1, pass@k-with-repair, iterations-to-green, and per-iteration gate vectors to `repair-loop-summary.json`.
- **End-to-end validation** (baseline gpt-5.5, runtime profile): `iter0 fail (plugin_check) → iter1 green`, autonomously — reproducing the manual result. Evidence: `evals/results/repair-loop-baseline-rt-20260622/`.
- Caveat: skill (claude) generation must run outside an active Claude Code session (nested `claude -p` is unreliable here); codex baselines and standalone/CI runs are unaffected.

## Cross-tier cheaper-model sweep (2026-06-22)

Question for the dev-tool market (WP devs without frontier tooling): does the loop carry the models a typical dev actually has — cheap APIs, local — to gate-clean, or only frontier ones? Same fixture, same runtime gate, repair loop with the warning-inclusive feedback fix.

| Tier | gate-clean? | iters-to-green | notes |
|---|---|---|---|
| gpt-5.5 medium (codex) | yes | 1 | failed only trivial metadata |
| gpt-5.5 low effort (codex) | yes | 1 | lowering effort was free |
| gemini-2.5-flash (cheap API) | yes | 2 | converged only after the feedback fix |
| qwen3.5 local, 262K ctx (ollama) | inconclusive | — | 0 output every iteration (timed out) |
| qwen2.5-coder:32b-q8 local (ollama) | inconclusive | — | iter0 timed out; then contract-shaped but incomplete (~1.8KB) packets, progressing 6→2→1 gate failures |

Findings:
- **The loop carries a cheap API model to gate-clean.** Flash reached a WPCS-clean, Plugin-Check-clean, WP-7.0-activating plugin in 2 repairs vs gpt-5.5's 1. Going cheap cost ~one extra iteration, not the outcome.
- **The lever is feedback quality, not model size.** Flash stalled at k=2 until `_failure_text` was fixed to feed WPCS WARNING detail (not just ERROR lines); with honest feedback it converged. Even the local coder, though incomplete, made monotonic contract progress (6→2→1), showing the loop guides weaker models too.
- **Local models were operationally finicky here** (shared GPU): memory contention blocked a second 32B; cold-start + slow large-context generation hit per-iteration timeouts; the coder's output looked length-capped/truncated. Environment artifacts, NOT clean capability fails — local is neither demonstrated to work nor shown to fail.

Harness changes this sweep forced (committed `3c08fde`): model-agnostic generation (ollama + gemini-REST providers via `--provider`); warning-inclusive repair feedback; tolerant generation (timeouts → graceful failure); `<think>`/code-fence stripping for local output; +6 unit tests (15 total).

## Negative space

- **N=1, single fixture, single-shot.** No variance/pass@k yet; the multi-stage *product* pipeline (buggy) was not measured. Stability across runs is unverified.
- **Gate = shippability, not deep behavior.** WPCS/Plugin Check/activation, not the ability-execution behavior smoke (which is coupled to exact artifact naming and was not run here).
- **Does not claim the skill is worse** — only that there is no measurable gate-pass edge either way on this fixture.
- Breadth requires authoring real fixtures for mcp-adapter / ai-client (currently example packets only).
