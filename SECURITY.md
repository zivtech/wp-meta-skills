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
Python 3.13.9 and uv 0.9.27 are exact bootstrap prerequisites. The Composer
command installs the pinned PHP toolchain for the real API and security gates;
without it, tool-dependent checks skip or report `blocked` (honest evidence,
never a pass):

```bash
uv lock --check
uv sync --locked --extra test
composer install --no-interaction --no-progress --no-scripts --no-plugins \
  --prefer-dist --working-dir evals/harness/php-tools
./install.sh --verify
uv run --locked --extra test python scripts/validate-distribution-parity.py
uv run --locked --extra test python scripts/validate-agent-frontmatter.py
uv run --locked --extra test python scripts/validate-wordpress-exact-api-contract.py
uv run --locked --extra test python scripts/validate-eval-suite-integrity.py \
  --strict-suites wordpress-plugin-executor \
  --strict-suites wordpress-block-executor \
  --strict-suites wordpress-security-critic \
  --strict-suites wordpress-performance-critic \
  --strict-suites wordpress-planner.migration \
  --strict-suites wordpress-blueprint-executor \
  --strict-suites wordpress-skill-candidate-eval \
  --allow-known-gaps
uv run --locked --extra test python -m pytest \
  -m "not docker_boundary and not live_provider" evals/harness/tests -q
uv run --locked --extra test python -m pytest \
  -m "docker_boundary and docker_sandbox and not live_provider" evals/harness/tests -q
uv run --locked --extra test python -m pytest \
  -m "docker_boundary and docker_generated_runtime and not live_provider" evals/harness/tests -q
```

The two Docker commands require the reviewed Linux Docker boundary and run in
separate no-secrets jobs. They are not host-Docker substitutes for one another.
The `live_provider` marker requires explicit operator authorization and is not
run in ordinary CI.

`uv.lock` is the canonical Python validation resolution. The committed
`requirements-validation.txt` is only a hash-pinned fallback when uv bootstrap
is unavailable:

```bash
python3.13 -m venv /tmp/wp-meta-skills-validation
/tmp/wp-meta-skills-validation/bin/python -m pip install --require-hashes \
  -r requirements-validation.txt
/tmp/wp-meta-skills-validation/bin/python -m pytest \
  -m "not docker_boundary and not live_provider" evals/harness/tests -q
```

Dependency updates require `uv lock --python 3.13.9` followed by a reviewed,
byte-identical export:

```bash
uv export --locked --extra test --no-emit-project --format requirements-txt \
  --output-file requirements-validation.txt
```

The parity command is local and network-free. It compares the five published
skill/agent/index surfaces, while the deterministic 57-file manifest binds
their exact bytes. Manifest verification fails closed when a listed surface is
missing, changed, symlinked, or not a regular file; it does not authenticate a
release or replace review of the prompt contracts.

## Non-Claims

Passing this validation bundle does not prove generated WordPress artifacts are
production-ready, broadly integrated, credentialed against third-party AI
providers, or secure in every deployment context. It proves only the explicit
contracts and oracle gates named by the relevant test or runtime smoke.
The Python lock does not lock Composer, Node, Docker, wp-env, browsers,
provider SDKs, provider models, or operator-only optimization environments.
