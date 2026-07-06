# Security Policy

## Scope

This repository contains prompt-only WordPress meta-skills, documentation, and
local validation harnesses. It does not ship a WordPress plugin, theme, service,
or hosted runtime.

Security reports are still in scope when they affect:

- unsafe generated-code guidance in WordPress planner, executor, or critic prompts;
- validation harness behavior that could hide unsafe generated artifacts;
- committed secrets, credentials, private endpoints, or real client data;
- reuse, provenance, or licensing claims that could mislead downstream users.

## Reporting

Report vulnerabilities privately through GitHub Security Advisories:
https://github.com/zivtech/wp-meta-skills/security/advisories/new
("Report a vulnerability" on the repository's Security tab). Maintainers will
acknowledge reports there and coordinate any fix and disclosure.

If you cannot use GitHub private vulnerability reporting, open a GitHub issue
that says only "security report — requesting private contact" without
technical details, and a maintainer will follow up.

Do not include live credentials, production tokens, or private client data in a
report. Use redacted snippets and reproduction steps.

## Validation Expectations

Run the standalone package validation bundle before release-facing changes.
The optional first command installs the pinned PHP toolchain for the
API-existence lint; without it, lint-dependent tests skip and the lint gate
reports `blocked` (honest evidence, never a pass):

```bash
composer install --working-dir evals/harness/php-tools  # optional, needs PHP >= 8.1
./install.sh --verify
python3 scripts/validate-agent-frontmatter.py
python3 scripts/validate-wordpress-exact-api-contract.py
python3 scripts/validate-eval-suite-integrity.py \
  --strict-suites wordpress-plugin-executor \
  --strict-suites wordpress-block-executor \
  --strict-suites wordpress-security-critic \
  --strict-suites wordpress-performance-critic \
  --strict-suites wordpress-planner.migration \
  --strict-suites wordpress-blueprint-executor \
  --strict-suites wordpress-skill-candidate-eval \
  --allow-known-gaps
python3 -m pytest \
  evals/harness/tests/test_invoke_claude_command.py \
  evals/harness/tests/test_wordpress_runtime_smoke.py \
  evals/harness/tests/test_wordpress_artifact_oracle.py \
  evals/harness/tests/test_wordpress_blueprint_launch_readiness.py \
  evals/harness/tests/test_wordpress_executor_packet_oracle.py \
  evals/harness/tests/test_wordpress_exact_api_contract.py \
  evals/harness/tests/test_wordpress_executor_artifact_certifier.py \
  evals/harness/tests/test_wordpress_packet_materializer.py \
  evals/harness/tests/test_wordpress_high_risk_answer_keys.py \
  evals/harness/tests/test_wordpress_high_risk_saved_outputs.py \
  evals/harness/tests/test_wordpress_skill_output_contract.py \
  evals/harness/tests/test_answer_key_score.py \
  evals/harness/tests/test_pairwise_pilot.py \
  evals/harness/tests/test_wordpress_candidate_pilot_generation.py \
  evals/harness/tests/test_wp_api_lint.py \
  evals/harness/tests/test_wp_security_gate.py \
  -q
```

## Non-Claims

Passing this validation bundle does not prove generated WordPress artifacts are
production-ready, broadly integrated, credentialed against third-party AI
providers, or secure in every deployment context. It proves only the explicit
contracts and oracle gates named by the relevant test or runtime smoke.
