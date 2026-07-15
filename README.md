# WP Meta Skills

[![skills.sh: zivtech/wp-meta-skills](https://img.shields.io/badge/skills.sh-zivtech%2Fwp--meta--skills-111111)](https://skills.sh/zivtech/wp-meta-skills)

A **verification-first toolchain for WordPress**: turn any model's output into gate-verified, shippable WordPress artifacts. Deterministic gates (WordPress Coding Standards, Plugin Check, `wp-env` activation) plus an automated repair loop do the work — so the value is *verified code*, not prompt magic, and it works with the model you already have.

> **Status:** initial public release. The pipeline is runnable today and model-agnostic; the supporting evidence is still **early and internal (n=1 fixture)**. Scope and boundaries are in *What the toolchain does*.

Discover and install the skills via [skills.sh](https://skills.sh/zivtech/wp-meta-skills): `npx skills add zivtech/wp-meta-skills`.

## The idea

LLM-written WordPress code looks plausible and ships broken. This toolchain closes that gap with a **loop, not a better prompt**:

```
generate → certify (deterministic WordPress gates) → feed the exact failures back → re-certify → green
           packet contract · API lint · security gate · WPCS · Plugin Check · wp-env activation · Abilities/MCP/AI runtime
```

- **Model-agnostic generation** — Claude, Codex/GPT, local Ollama, or Gemini, via one `--provider` flag.
- **Real gates** — actual WordPress tooling (PHPCS/WPCS, Plugin Check, `wp-env`, PHPUnit) plus deterministic API-existence and security sidecars, not an LLM judge.
- **Automated repair** — the loop feeds each deterministic failure back to the model and re-certifies until the artifact passes or a budget is hit.

## What the toolchain does

- **Converts a model's near-miss into a gate-clean artifact** — WPCS-clean, Plugin Check-clean, activates in WordPress 7.0. Early internal evidence on one Abilities-API fixture: a frontier model reaches green in **1** repair, a **cheap API model (Gemini Flash) in 2**. The lever is **feedback quality, not model size**.
- **Routes any model to the same gates** — frontier, cheap API, or local — through one `--provider` flag, with an identical loop and identical deterministic gates.
- **Puts the value in verified code, not prompt wording** — the durable asset is the gate + repair pipeline. Honest scope: across internal diagnostics (pairwise, answer-key, gate-pass, GEPA) the personas roughly match a strong baseline, so this makes no claim the prompts make a model "better at WordPress"; the gates measure shippability, not deep behavior; and local-model support is operationally heavier and not yet cleanly benchmarked.
- Evidence + methodology: [`executor-gate-pass-experiment-2026-06-22.md`](docs/wordpress/executor-gate-pass-experiment-2026-06-22.md), [`gepa-executor-spike-2026-06-22.md`](docs/wordpress/gepa-executor-spike-2026-06-22.md), [`skill-improvement-research-2026-06-20.md`](docs/wordpress/skill-improvement-research-2026-06-20.md).

## Quickstart — the repair loop

Generate → gate → auto-repair, with whatever model you have:

```bash
# cheap API (Gemini Flash via GOOGLE_API_KEY)
python3 evals/harness/run_executor_repair_loop.py \
  --suite wordpress-plugin-executor --fixture abilities-ai-surface-v1 \
  --provider gemini --model gemini-2.5-flash \
  --profile runtime --max-repairs 3 --run-id demo-flash

# local model (Ollama)
python3 evals/harness/run_executor_repair_loop.py \
  --suite wordpress-plugin-executor --fixture abilities-ai-surface-v1 \
  --provider ollama --model qwen2.5-coder:32b-instruct-q8_0 \
  --profile runtime --max-repairs 3 --run-id demo-local
```

Reports `pass@1`, `pass@k`-with-repair, iterations-to-green, and per-iteration gate vectors to `repair-loop-summary.json`. Use `--profile static` for a fast, Docker-free contract check before spending on the runtime gate.

## The deterministic gates (use directly)

The repair loop composes these; you can also run them standalone.

```bash
# Full composed chain: packet contract → materialize → static artifact checks
python3 evals/harness/certify_wordpress_executor_artifact.py \
  --executor plugin --packet <packet.md> --out-dir <art-dir> --result-dir <res-dir> --overwrite

# Provisioned runtime gate: WPCS + Plugin Check + wp-env activation (Docker)
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path <art-dir>/<plugin-slug> --artifact-kind plugin \
  --provision-full-profile --strict-full-profile --write --run-id <id> --timeout-sec 600

# Contract + output oracles
python3 scripts/validate-wordpress-exact-api-contract.py
python3 evals/harness/validate_wordpress_executor_packet.py --executor plugin --packet <packet.md>
python3 evals/harness/validate_wordpress_skill_output.py --skill wordpress-critic --output <output.md>

# Security gate sidecar + critic contract
python3 evals/harness/wp_security_gate.py --path <generated-plugin-dir> --out security-gate.json
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-security-critic \
  --output <critic-output.md> \
  --security-gate security-gate.json
```

`--executor` accepts `plugin`, `block`, or `blueprint`. Static artifact passes are **not** runtime proof; reserve `--profile runtime` / `--provision-full-profile` for the real contract. The security gate catches deterministic WPCS security findings and suppression abuse; the security critic still owns reachability, authorization, and exploitability judgment.

The repair loop uses one fail-closed executor/profile matrix:

| Executor | Static | Runtime |
|---|---|---|
| Plugin | Supported | Supported by the isolated `standard` profile |
| Block | Supported | Conditional: the selected fixture metadata must declare exact `block_name`, `frontend_selector`, and `expected_frontend_text` assertions |
| Blueprint | Supported | Rejected |

Block runtime carries those fixture-owned assertions through the same staged,
inspected no-egress runtime used for activation. It requires the exact block
registration plus selector-scoped editor/save/frontend proof; it never infers
the assertion from generated output. Blueprint repair is static-only. The
separate Blueprint launch preflight and browser smoke are not automated by the
repair loop and are not a fallback for `--profile runtime`.

No tracked block-executor fixture currently declares `runtime_assertions`, so
the conditional block repair lane is implemented and integration-tested but no
current repair fixture is runtime-eligible. Direct runtime-harness assertion
flags are operator-supplied evidence inputs; only the repair-loop fixture loader
establishes that they came from a canonical fixture pair.

## The skill lifecycle

Planners → executors → critics produce the packets the gates verify — inputs to the pipeline above, not a substitute for it.

- `/wordpress-planner` for broad architecture; focused planners for content models, plugins, blocks, themes, and migrations.
- Executors generate materializable packets once a plan has enough detail.
- Critics review plans and implementations.

## Status & caveats

- Initial public release. Evidence is **n=1 fixture**; broader benchmarking (more fixtures, a clean local-model run, variance) is pending before any public performance claim.
- Known harness gaps: the bundled golden example packet is not yet gate-clean; the multi-stage `--mode executor` path mangles output (use the repair loop / single-shot generation); local-model runs need a dedicated, non-contended environment.

## Naming, affiliation, and license

- This project is maintained by [Zivtech](https://www.zivtech.com/) and is **not affiliated with or endorsed by the WordPress Foundation, WordPress.org, or Automattic**. "WordPress" is a registered trademark of the WordPress Foundation; this toolchain is *for* WordPress.
- This repository is licensed under [GPL-3.0](LICENSE) (relicensed from Apache-2.0 on 2026-07-03, before first public release; all content is original Zivtech work, so no third-party grants were affected). Code that these skills *generate* for you (plugins, blocks, themes, Blueprints) is not a derivative of this repository: you own it and may license it as you choose, including GPLv2-or-later for WordPress.org directory distribution.

## See also

- [`AGENTS.md`](AGENTS.md) — agent registry and lifecycle map
- [`docs/wordpress/lifecycle.md`](docs/wordpress/lifecycle.md) — planner → executor → critic flow
- [`docs/wordpress/runtime-oracle-runbook.md`](docs/wordpress/runtime-oracle-runbook.md) — gate/oracle commands and evidence semantics
- [`docs/wordpress/executor-gate-pass-experiment-2026-06-22.md`](docs/wordpress/executor-gate-pass-experiment-2026-06-22.md) — the gate-pass + cheaper-model evidence
- [`docs/wordpress/gepa-executor-spike-2026-06-22.md`](docs/wordpress/gepa-executor-spike-2026-06-22.md) — machine-optimized persona vs the gate (the repair loop remains the lever)
- [`docs/wordpress/skill-improvement-research-2026-06-20.md`](docs/wordpress/skill-improvement-research-2026-06-20.md) — why the focus shifted to verification + repair
- [`docs/wordpress/v1-completion-todo.md`](docs/wordpress/v1-completion-todo.md) — remaining work before standalone release
