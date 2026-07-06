# AGENTS.md - wordpress-skills

## Agent Registry

| Agent | Type | Model | Command | Companion |
|---|---|---|---|---|
| wordpress-planner | planner | claude-fable-5 | `/wordpress-planner` | wordpress-critic |
| wordpress-content-model-planner | planner | claude-fable-5 | `/wordpress-planner.content-model` | wordpress-critic, wordpress-theme-critic |
| wordpress-plugin-planner | planner | claude-fable-5 | `/wordpress-planner.plugin` | wordpress-security-critic, wordpress-critic |
| wordpress-block-planner | planner | claude-fable-5 | `/wordpress-planner.block` | wordpress-critic, wordpress-performance-critic |
| wordpress-theme-planner | planner | claude-fable-5 | `/wordpress-planner.theme` | wordpress-theme-critic |
| wordpress-migration-planner | planner | claude-fable-5 | `/wordpress-planner.migration` | wordpress-critic |
| wordpress-blueprint-executor | executor | claude-sonnet-4-6 | `/wordpress-blueprint-executor` | wordpress-critic |
| wordpress-plugin-executor | executor | claude-sonnet-4-6 | `/wordpress-plugin-executor` | wordpress-security-critic, wordpress-critic |
| wordpress-block-executor | executor | claude-sonnet-4-6 | `/wordpress-block-executor` | wordpress-critic, wordpress-performance-critic |
| wordpress-theme-executor | executor | claude-sonnet-4-6 | `/wordpress-theme-executor` | wordpress-theme-critic |
| wordpress-critic | critic | claude-fable-5 | `/wordpress-critic` | wordpress-planner |
| wordpress-theme-critic | critic | claude-fable-5 | `/wordpress-theme-critic` | wordpress-theme-planner |
| wordpress-security-critic | critic | claude-fable-5 | `/wordpress-security-critic` | wordpress-plugin-planner |
| wordpress-performance-critic | critic | claude-fable-5 | `/wordpress-performance-critic` | wordpress-planner |

## WordPress Lifecycle

1. Plan with `/wordpress-planner` or a focused planner. Mature V1 planners require current-state evidence, WordPress-native decisions, exact WordPress API/hook/file/command names where relevant, assumptions, verification strategy, acceptance criteria, and critic checkpoints.
2. Generate artifacts with a WordPress executor when the plan is sufficiently specific. Executors must preserve spec fidelity, stop on critical ambiguity, log deviations, name exact implementation surfaces, and produce verification packets.
3. Review with the general critic plus the focused critic for theme, security, or performance risk. Critics must use evidence-backed findings, severity calibration, exact remediation APIs, gap analysis, and false-positive control.
4. Revise and re-review before treating generated work as production-ready.

## Evaluation Status

V1 protocols are complete for in-repo use, with a 2026-06-20 Exact API and Verification Contract amendment. The upstream candidate suite is closed as directional-internal for frontier-model review quality: pairwise and answer-key diagnostics do not establish a Zivtech quality edge over a strong few-shot prompt. The 27-fixture superiority benchmark remains blocked.

Use `docs/wordpress/v1-completion-todo.md` as the ordered checklist before treating this collection as complete or preparing a standalone `wp-meta-skills` public repo. Use `docs/wordpress/runtime-oracle-runbook.md` for packet, static artifact, and runtime-tool evidence semantics; `docs/wordpress/skill-improvement-research-2026-06-20.md` for the current research-backed improvement direction; `docs/wordpress/candidate-pilot-runbook.md` for historical candidate-pilot mechanics; and `docs/wordpress/license-reuse-policy.md` for reuse boundaries.
