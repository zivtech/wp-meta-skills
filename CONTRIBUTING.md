# Contributing

`wp-meta-skills` is a prompt-only WordPress skill package. Contributions should
improve the skill contracts, WordPress API specificity, validation harnesses, or
evidence quality.

## Working Rules

- Keep generated examples free of secrets, credentials, private URLs, and real
  client data.
- Name exact WordPress APIs, hooks, files, packages, commands, or verification
  surfaces when a claim depends on them.
- Preserve negative space: say what a proof does not cover.
- Prefer deterministic contracts and runtime oracles over generic review-quality
  claims.
- Do not copy or closely adapt upstream prompt text unless the source license,
  attribution, and reuse ledger entry are resolved first.

## Validation

Most contributions can be validated directly in this repository. If you edit
any tracked file, regenerate the checksum manifest first:

```bash
./install.sh --generate-manifest
```

(`scripts/build-wp-meta-skills-package.py` lives in the private
`zivtech-meta-skills` source monorepo, not in this repository; it only matters
for maintainers regenerating the whole package. See `PROVENANCE.md`.)

Install Python 3.13.9 and uv 0.9.27, then create the exact validation
environment from the resolver lock. The pinned PHP toolchain is also required
for the real API and security gates; without it those gates report `blocked` or
skip rather than proving the full general partition.

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
```

The remaining required partitions run separately on Linux with a supported
Docker Engine. They are disjoint from the general partition and from each
other; the live-provider marker is never part of ordinary validation.

```bash
uv run --locked --extra test python -m pytest \
  -m "docker_boundary and docker_sandbox and not live_provider" evals/harness/tests -q
uv run --locked --extra test python -m pytest \
  -m "docker_boundary and docker_generated_runtime and not live_provider" evals/harness/tests -q
```

When changing a direct Python dependency, update and review both resolver
artifacts:

```bash
uv lock --python 3.13.9
uv export --locked --extra test --no-emit-project --format requirements-txt \
  --output-file requirements-validation.txt
```

`uv.lock` is canonical. If uv bootstrap is temporarily unavailable, the
committed pip export is a tested installation escape hatch for the general
partition only:

```bash
python3.13 -m venv /tmp/wp-meta-skills-validation
/tmp/wp-meta-skills-validation/bin/python -m pip install --require-hashes \
  -r requirements-validation.txt
/tmp/wp-meta-skills-validation/bin/python -m pytest \
  -m "not docker_boundary and not live_provider" evals/harness/tests -q
```

This lock covers only repository Python validation. It does not lock Composer,
Node, Docker, wp-env, browsers, provider SDKs, provider models, or operator-only
optimization environments.

The distribution parity gate compares all five publication surfaces:
`.claude/skills`, `.agents/skills`, `.claude/agents`, `.codex/agents`, and
`skills.sh.json`. `MANIFEST.sha256` is a deterministic 57-file checksum control
for those surfaces. After an intentional publication change, regenerate the
manifest, review its diff, and then run `./install.sh --verify`; verification
fails closed on missing, extra, symlinked, non-regular, or changed distribution
files.

The symbol snapshot test is hermetic: it checks the committed source hashes,
Composer-lock identities, container inventory, and normalized symbol digest.
When those pinned inputs intentionally change, maintainers rebuild separately:

```bash
python3 scripts/build-wp-symbol-db.py --wp-version 7.0 \
  --out /tmp/wp-symbols-rebuild.json
cmp -s /tmp/wp-symbols-rebuild.json evals/harness/data/wp-symbols.json
```

The rebuild requires the reviewed Composer platform image to be present locally
and fetches only the two immutable `raw.githubusercontent.com` source paths. It
is not an ordinary CI step.

Provider metadata smoke is a separate, explicitly authorized manual gate. It
uses the same trusted-curl/header-FD path as the repair loop, performs no content
generation, and prints no credential or provider response:

```bash
WP_META_SKILLS_LIVE_PROVIDER_AUTHORIZED=1 \
GEMINI_LIVE_MODEL="$GEMINI_MODEL" uv run --locked --extra test python -m pytest \
  evals/harness/tests/test_provider_preflight.py \
  -m live_provider -q
```

The authorization sentinel must be set exactly to `1`. Set `GEMINI_MODEL` to
an operator-selected current model and provide
`GOOGLE_API_KEY` or `GEMINI_API_KEY` in the environment. Do not add this marker
to ordinary CI. A pass proves TLS/header transport, exact metadata identity, and
metadata-advertised `generateContent`; it does not prove generation quota or
billing authorization.

## Standalone installer ownership

`install.sh` owns only links whose existing targets resolve inside the
`wp-meta-skills` checkout running the command. Normal installation preserves
unrelated and dangling symlinks as well as every regular file or directory.
`--remove` deletes only existing links owned by that checkout.

`--force` is an install-only recovery boundary. It may replace an unrelated or
dangling symlink at a known skill or agent destination; it never replaces a
regular file or directory. Before replacement, the installer prints the exact
destination and a shell-escaped copy of the prior raw link target. Preserve
that line until installation completes so the link can be reconstructed if the
operation is interrupted. The option does not inspect or read target contents.

Plan 010 also requires the two-profile artifact-certification measurement after
the pinned Composer toolchain is installed:

```bash
uv run --locked --extra test python scripts/measure-plan010-artifact-path.py \
  --profile ci \
  --output tmp/plan010-artifact-measurement.json
```

The aggregate profile reaches the reviewed file, byte, metadata-edge, PHP-set,
and runtime-closure limits. The separate maximum-member profile reaches the
8 MiB runtime-member limit, which cannot coexist with 64 nonempty PHP files
inside the 8 MiB aggregate PHP limit. This is certification-path evidence, not
a WordPress frontend, database, production-throughput, or concurrency claim.
The record includes both authenticated PHP scanner-alias copy passes so unusual
suffix candidates cannot disappear behind PHPStan or PHPCS extension filters.

## Reuse And Provenance

Reference-only upstream comparison is allowed. Direct copied or closely adapted
prompt text requires a source URL, commit or access date, license, local file,
adapted section, and rationale in the reuse ledger before it lands.

When in doubt, keep the production skill text clean-room and cite the upstream
project as a comparator rather than importing its wording.
## Sandbox inventory updates

Plan 009 runtime inputs are reviewed in `evals/harness/container-images.json`.
An update must record the immutable OCI index digest, linux/amd64 and
linux/arm64 child manifests, source tag, verification date, purpose, and
license. Update the repository runner lock with scripts disabled, verify its
registry integrity, run the hermetic provisioning/materialization tests, and
run the separate no-secrets GitHub-hosted Linux Docker feasibility job against
the exact commit. Mutable tags, unreviewed helper images, local Docker Desktop
results, and generated lock synthesis are not acceptable substitutes. The
legacy canary slice requires at least 20 GiB free, permits at most a
conservative 12 GiB post-run delta (leaving an 8 GiB reserve), and has a causal
30-minute process timeout. The aggregate no-secrets job has a 60-minute envelope
because the package-acquisition boundary runs before that slice. A budget
failure blocks the checkpoint.

The generated-code runtime uses the same inventory but has a separate required
Linux gate:

```bash
uv run --locked --extra test python -m pytest \
  -m "docker_boundary and docker_generated_runtime and not live_provider" \
  evals/harness/tests -q
```

That gate never receives Actions secrets. It builds from the recorded platform
digests and committed build-input hashes, then proves generated PHP and browser
JavaScript inside the repository-owned isolated topology. Do not substitute a
host `wp-env`, host browser, Docker Desktop result, mutable image tag, or cached
local image for this gate.

The generated runtime runs in its own required job. Its process has a causal
30-minute timeout inside a 35-minute job envelope reserved for cleanup. The job
requires 20 GiB free before any runtime pull/build and permits at most a 12 GiB
disk delta after its exact run-owned containers, networks, and image tags are
removed. The post-cleanup measurement includes residual image layers and build
cache; exceeding it fails the job.

The acquisition proxy allowlist is limited to the reviewed npm and Composer
registry endpoints represented by the committed locks. The final generated-code
runtime has no public acquisition route: the browser can reach only the exact
WordPress gateway origin, WordPress and CLI can reach only the database peer,
and the database has no application-facing peer beyond that backend network.
Each final bridge is both `internal` and configured with Docker's IPv4 gateway
mode `isolated`; live inspection requires no host bridge address and each
generated-code container must have no default route. The generated runtime
therefore requires Docker Engine 28 or newer and blocks before provisioning on
older or unparseable daemon versions.
Widening either allowlist is a security change requiring inventory review,
hostile-route canaries, both test profiles, and a new hosted Linux proof.
