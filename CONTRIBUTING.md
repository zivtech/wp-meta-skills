# Contributing

Contributions to `wp-meta-skills` should improve the WordPress skill contracts,
API specificity, validation harness, or evidence quality without overstating
what the repository proves.

## Working Rules

- Keep generated examples free of secrets, credentials, private URLs, and real
  client data.
- Name exact WordPress APIs, hooks, files, packages, commands, and verification
  surfaces when a claim depends on them.
- State negative space: say what a proof does not cover.
- Prefer deterministic contracts and runtime oracles to generic quality claims.
- Do not copy or closely adapt upstream prompt text until its license,
  attribution, and reuse-ledger entry have been reviewed.
- Treat this standalone repository as the active edit source. The earlier
  monorepo package build is historical provenance, described in
  [PROVENANCE.md](PROVENANCE.md).

## Validation

Use Python 3.13.9 and uv 0.9.27. The locked Python environment is canonical;
the pinned Composer toolchain is also required for the full API and security
gates.

Regenerate the checksum manifest after any intentional change to a tracked
distribution surface, then run the locked validation sequence:

```bash
./install.sh --generate-manifest
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
uv run --locked --extra test python scripts/validate-public-docs.py
uv run --locked --extra test python -m pytest \
  -m "not docker_boundary and not live_provider" evals/harness/tests -q
```

The remaining required partitions run separately on Linux with a supported
Docker Engine. They are disjoint from the general partition and from each
other. The live-provider marker is not part of ordinary validation.

```bash
uv run --locked --extra test python -m pytest \
  -m "docker_boundary and docker_sandbox and not live_provider" \
  evals/harness/tests -q
uv run --locked --extra test python -m pytest \
  -m "docker_boundary and docker_generated_runtime and not live_provider" \
  evals/harness/tests -q
```

`uv.lock` is authoritative. When changing a direct Python dependency, update
and review both resolver artifacts:

```bash
uv lock --python 3.13.9
uv export --locked --extra test --no-emit-project \
  --format requirements-txt --output-file requirements-validation.txt
```

If uv bootstrap is temporarily unavailable, the committed, hash-locked pip
export is a tested installation fallback for the general partition only:

```bash
validation_venv="$(mktemp -d "${TMPDIR:-/tmp}/wp-meta-skills-validation.XXXXXX")"
trap 'rm -rf "$validation_venv"' EXIT
python3.13 -m venv "$validation_venv"
"$validation_venv/bin/python" -m pip install --require-hashes \
  -r requirements-validation.txt
"$validation_venv/bin/python" -m pytest \
  -m "not docker_boundary and not live_provider" evals/harness/tests -q
```

The Python lock does not lock Composer, Node, Docker, `wp-env`, browsers,
provider SDKs, provider models, or operator-only optimization environments.

## Distribution Controls

The parity gate compares `.claude/skills`, `.agents/skills`, `.claude/agents`,
`.codex/agents`, and `skills.sh.json`. `MANIFEST.sha256` is the checksum control
for those publication surfaces. Review its diff after regeneration;
`./install.sh --verify` fails on missing, extra, symlinked, non-regular, or
changed distribution files.

The committed WordPress symbol snapshot is checked hermetically against its
source hashes, Composer locks, container inventory, and normalized symbol
digest. Rebuilding the snapshot is a separate maintainer operation with
reviewed immutable inputs; it is not an ordinary CI step.

## Provider and Runtime Boundaries

Live provider metadata smoke requires explicit operator authorization and a
current operator-selected model. It performs metadata lookup, not content
generation, and must never print a credential or provider response. A pass
does not prove generation quota or billing authorization.

The Docker partitions run without Actions secrets. They require the recorded
image digests and build-input hashes, isolated networking, causal timeouts,
run-owned cleanup, a 20 GiB admission floor, and the reviewed post-run disk
delta. A host `wp-env`, Docker Desktop result, mutable tag, or cached local image
is not a substitute for the required hosted Linux boundary.

## Reuse and Provenance

Reference-only upstream comparison is allowed. Direct copied or closely
adapted prompt text requires a source URL, commit or access date, license,
local file, adapted section, and rationale in the reuse ledger before it lands.
When in doubt, keep production skill text clean-room and cite the upstream
project only as a comparator.
