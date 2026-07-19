# WP Meta Skills

[![skills.sh: zivtech/wp-meta-skills](https://img.shields.io/badge/skills.sh-zivtech%2Fwp--meta--skills-111111)](https://www.skills.sh/zivtech/wp-meta-skills)

WP Meta Skills is a verification-first WordPress skill and harness collection.
It combines planner, executor, and critic instructions with deterministic checks
for generated WordPress artifacts. As observed on 2026-07-15, the
[GitHub repository](https://github.com/zivtech/wp-meta-skills) was public and
[skills.sh](https://www.skills.sh/zivtech/wp-meta-skills) listed 14 skills.

That external state is dated; the current project snapshot is maintained through the
[stable status pointer](docs/wordpress/project-status-current.md). Evidence
scope and proof boundaries are documented in [EVIDENCE.md](EVIDENCE.md).

## What ships

- WordPress planners for broad architecture, content models, plugins, blocks,
  themes, and migrations.
- Executors for plugins, blocks, themes, and WordPress Playground Blueprints.
- General, theme, security, and performance critics.
- A repair-loop workflow that can send deterministic gate failures back to a
  selected model and stop when the artifact passes or the repair budget ends.
- Static and runtime gates for packet conformance, WordPress API existence,
  security findings, WPCS, Plugin Check, activation, and selected browser
  assertions.

The repository includes hermetic tests for the repair-loop orchestration and
its fail-closed executor/profile matrix. It does not include committed evidence
that establishes general repair convergence, model superiority, production
readiness, or security assurance. A passing static profile is not runtime
proof, and a passing runtime smoke is not production proof.

## Install the skills

```bash
npx skills add zivtech/wp-meta-skills
```

The local installer can also link the shipped skills and agents into supported
Claude and Codex discovery directories:

```bash
./install.sh
./install.sh --verify
```

The installer owns only links whose targets resolve inside the checkout that
created them. See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete validation
contract.

## Repair-loop workflow

The repair loop accepts an exact provider/model selection, invokes an executor,
certifies the resulting packet, and returns deterministic failures for a
bounded repair attempt:

```bash
# API provider. GEMINI_MODEL must be an exact model ID available to the key.
python3 evals/harness/run_executor_repair_loop.py \
  --suite wordpress-plugin-executor \
  --fixture abilities-ai-surface-v1 \
  --provider gemini \
  --model "$GEMINI_MODEL" \
  --profile runtime \
  --max-repairs 3 \
  --run-id demo-gemini

# Local provider. OLLAMA_MODEL must be an exact tag from `ollama list`.
python3 evals/harness/run_executor_repair_loop.py \
  --suite wordpress-plugin-executor \
  --fixture abilities-ai-surface-v1 \
  --provider ollama \
  --model "$OLLAMA_MODEL" \
  --profile static \
  --max-repairs 3 \
  --run-id demo-local
```

The workflow writes a sanitized provider preflight receipt and a repair-loop
summary with the observed iteration and gate results. Gemini credentials are
sent through a header file descriptor; they are not placed in URLs, process
arguments, receipts, or diagnostics. Metadata preflight proves only the exact
model identity and advertised `generateContent` method at that moment. It does
not prove a generation request, quota, billing authorization, or future model
availability.

## Deterministic gates

```bash
# Packet contract, materialization, and static artifact checks.
python3 evals/harness/certify_wordpress_executor_artifact.py \
  --executor plugin \
  --packet <packet.md> \
  --out-dir <artifact-dir> \
  --result-dir <result-dir> \
  --overwrite

# Provisioned WPCS, Plugin Check, and activation smoke.
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path <artifact-dir>/<plugin-slug> \
  --artifact-kind plugin \
  --provision-full-profile \
  --strict-full-profile \
  --write \
  --run-id <id> \
  --timeout-sec 600

# Repository and output contracts.
python3 scripts/validate-wordpress-exact-api-contract.py
python3 evals/harness/validate_wordpress_executor_packet.py \
  --executor plugin --packet <packet.md>
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-critic --output <output.md>

# Security sidecar and critic consumption.
python3 evals/harness/wp_security_gate.py \
  --path <generated-plugin-dir> --out security-gate.json
python3 evals/harness/validate_wordpress_skill_output.py \
  --skill wordpress-security-critic \
  --output <critic-output.md> \
  --security-gate security-gate.json
```

The security gate catches configured WPCS security findings and suppression
abuse. The security critic still owns contextual analysis of reachability,
authorization, and exploitability.

The repair-loop executor/profile matrix is fail-closed:

| Executor | Static profile | Runtime profile |
|---|---|---|
| Plugin | Supported | Supported by the isolated `standard` profile |
| Block | Supported | Requires fixture-owned block, selector, and text assertions |
| Blueprint | Supported | Rejected |

No tracked block-executor fixture currently declares the required runtime
assertions. The conditional block lane is implemented and integration-tested,
but no current repair fixture is runtime-eligible. Blueprint repair remains
static-only; its separate launch audit and browser smoke are operator-run tools,
not a substitute for repair-loop runtime support.

## Evidence boundaries

The bundled evidence is narrow and historical. It can support the specific
claims named in [EVIDENCE.md](EVIDENCE.md); it cannot establish broad model
quality, benchmark superiority, security, production behavior, or long-run
variance. Provider and runtime commands may also require credentials, Docker,
network access, or operator authorization that ordinary validation does not
exercise.

## Naming, affiliation, and license

This project is maintained by [Zivtech](https://www.zivtech.com/) and is not
affiliated with or endorsed by the WordPress Foundation, WordPress.org, or
Automattic. “WordPress” is a registered trademark of the WordPress Foundation;
this is a toolchain for WordPress.

The repository is licensed under [GPL-3.0](LICENSE). It was relicensed from
Apache-2.0 on 2026-07-03 before the first public import; all repository content
is original Zivtech work. Generated plugins, blocks, themes, and Blueprints are
not derivatives of this repository and may use an appropriate project license,
including GPLv2-or-later for WordPress.org distribution.

## Reference documentation

- [Agent registry and lifecycle](AGENTS.md)
- [Planner → executor → critic flow](docs/wordpress/lifecycle.md)
- [Runtime oracle runbook](docs/wordpress/runtime-oracle-runbook.md)
- [Gutenberg cross-repo hardening plan and execution record](docs/wordpress/gutenberg-cross-repo-hardening-2026-07-16.md)
- [Verification toolchain visual explainer](docs/wordpress/wp-verification-toolchain-explainer.html)
- [Current project status](docs/wordpress/project-status-current.md)
- [Evidence map](EVIDENCE.md)
- [Contribution and validation contract](CONTRIBUTING.md)
