# wp-meta-skills

WordPress-focused planner, executor, and critic skill collection from the Zivtech meta-skills ecosystem, packaged as the standalone `wp-meta-skills` repository.

## Purpose

This collection gives WordPress the same lifecycle shape as the Drupal skill ecosystem: plan before building, generate artifacts from an approved spec, then review the result with focused critics.

## V1 Scope

- Architecture planning for plugins, blocks, themes, content models, migrations, and operations.
- Executors for Playground blueprints, plugins, blocks, and themes.
- Critics for general WordPress quality, theme quality, security, and performance.
- Evaluation-first candidate catalog and smoke-tier eval scaffolding.

## Important Files

| File | Purpose |
|---|---|
| `AGENTS.md` | Agent registry and lifecycle map |
| `docs/wordpress/candidate-catalog.md` | Surveyed upstream skill candidates with commit/license data |
| `docs/wordpress/coverage-matrix.md` | Drupal-equivalent and WordPress-native coverage matrix |
| `docs/wordpress/provenance-policy.md` | Rules for GPL-compatible reuse and attribution |
| `docs/wordpress/license-reuse-policy.md` | Conservative license handling for skill prompt text |
| `docs/wordpress/lifecycle.md` | Planner -> executor -> critic flow |
| `docs/wordpress/runtime-oracle-runbook.md` | Packet, static artifact, and runtime-tool oracle commands and evidence semantics |
| `docs/wordpress/v1-completion-todo.md` | Ordered checklist for finishing V1 before standalone public release |
| `docs/wordpress/skill-improvement-research-2026-06-20.md` | Research synthesis and evidence-based improvement direction after pairwise and answer-key diagnostics |

## Reuse Policy

This repository is licensed under GPL-3.0 (root `LICENSE`; relicensed from Apache-2.0 on 2026-07-03, before first public release). Direct copied or closely adapted third-party prompt text remains excluded from the V1 skill prompts: all skill text is clean-room Zivtech writing, and upstream projects are reference-only comparators recorded in `docs/wordpress/reuse-ledger.md`. Clean-room original Zivtech text does not need passage-level attribution, but it should still list compatible references in the relevant skill file. Any future direct adaptation of third-party text requires a license-compatibility check (GPL-compatible sources now qualify) plus a reuse-ledger entry per `docs/wordpress/license-reuse-policy.md`.

## Evaluation Boundary

Do not claim that V1 outperforms upstream or baseline prompts. The 2026-06-17 through 2026-06-20 evidence closes the frontier-model per-task review-quality claim as internal-only:

1. Pairwise diagnostics showed `zivtech_prototype` as top-tier but not certified and not separated from a strong few-shot prompt.
2. The fast and adversarial answer-key diagnostics showed no measurable detection/specificity edge and a small API-naming deficit.
3. The 27-fixture superiority benchmark remains blocked unless the measurement target changes.

The current improvement target is narrower and testable: exact WordPress API naming, verification-oracle handoffs, cheaper-model lift, output-contract conformance via `validate_wordpress_skill_output.py`, variance reduction, and executor tasks with deterministic packet, static artifact, and provisioned runtime WordPress checks.
