# Provenance

`wp-meta-skills` is prepared from the WordPress skill suite inside the
`zivtech-meta-skills` monorepo.

## Source Shape

The standalone package is generated from several source areas:

- WordPress agents and skills from `wordpress-skills/.claude/`.
- WordPress documentation from `wordpress-skills/docs/`.
- WordPress package metadata from `wordpress-skills/standalone/`.
- WordPress eval suites from `evals/suites/wordpress-*`.
- The pruned WordPress validation harness from `evals/harness/`.
- Shared validation scripts from `scripts/`.
- The root `install.sh` manifest verifier.

The package moves the WordPress skill surface to root `.claude/agents/` and
`.claude/skills/` so Claude and Codex skill discovery do not depend on the old
monorepo layout.

## Build Command

Build from the source repo root:

```bash
python3 scripts/build-wp-meta-skills-package.py \
  --output /tmp/wp-meta-skills-pruned-20260621 \
  --force \
  --generate-manifest
```

The generated package includes `PACKAGE-BUILD.md`, `MANIFEST.sha256`, and the
selected evidence bundle under `evidence/wordpress-skill-candidate-eval/`.

## History Strategy

The first public draft should use a clean import of the generated package with
this provenance file preserved.

A raw subtree split of `wordpress-skills` is not enough for the current package:
it would omit root-level harness files, validation scripts, `install.sh`, and
selected evidence files copied from `evals/results/`.

If maintainers require history preservation instead of clean import, create a
release commit first and use a path-aware filtering strategy over every source
area listed above. Do not claim a history-preserving import until the resulting
repository has been validated against the same package gates.

## Non-Claims

This provenance file does not prove public release, owner review, live GitHub
Actions, or long-run model-variance reduction. Those remain release gates until
they are verified on the public repository.
