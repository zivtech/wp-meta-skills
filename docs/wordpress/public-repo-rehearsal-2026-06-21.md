# Public Repo Rehearsal - 2026-06-21

## Purpose

This rehearsal tests the documented first-draft history strategy for
`wp-meta-skills`: clean-import the generated package with `PROVENANCE.md`
preserved, then run the standalone validation gates from the imported repo.

This is a local rehearsal only. It does not create a public GitHub repository,
run GitHub Actions, or publish result archives.

## Commands

Run from the `zivtech-meta-skills` repo root:

```bash
python3 scripts/build-wp-meta-skills-package.py \
  --output /tmp/wp-meta-skills-pruned-20260621 \
  --force \
  --generate-manifest

rm -rf /tmp/wp-meta-skills-public-rehearsal-20260621
cp -R /tmp/wp-meta-skills-pruned-20260621 \
  /tmp/wp-meta-skills-public-rehearsal-20260621

cd /tmp/wp-meta-skills-public-rehearsal-20260621
git init -b main
git add .
git commit -m "chore: import wp-meta-skills standalone package"
```

Then validate from the local rehearsal repo:

```bash
PYTHONDONTWRITEBYTECODE=1 ./install.sh --verify
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate-agent-frontmatter.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate-wordpress-exact-api-contract.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate-eval-suite-integrity.py \
  --strict-suites wordpress-plugin-executor \
  --strict-suites wordpress-block-executor \
  --strict-suites wordpress-skill-candidate-eval \
  --allow-known-gaps
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  evals/harness/tests/test_invoke_claude_command.py \
  evals/harness/tests/test_wordpress_runtime_smoke.py \
  evals/harness/tests/test_wordpress_artifact_oracle.py \
  evals/harness/tests/test_wordpress_executor_packet_oracle.py \
  evals/harness/tests/test_wordpress_exact_api_contract.py \
  evals/harness/tests/test_wordpress_executor_artifact_certifier.py \
  evals/harness/tests/test_wordpress_packet_materializer.py \
  evals/harness/tests/test_wordpress_skill_output_contract.py \
  evals/harness/tests/test_answer_key_score.py \
  evals/harness/tests/test_pairwise_pilot.py \
  evals/harness/tests/test_wordpress_candidate_pilot_generation.py \
  -q
```

## Evidence

The local rehearsal proved:

- The generated package can be initialized as a standalone git repo on `main`.
- The clean-import root commit includes the generated WordPress package files.
- `./install.sh --verify` passes after import.
- Agent frontmatter validation passes after import.
- WordPress Exact API contract validation passes after import.
- Strict selected WordPress suite validation passes after import.
- The WordPress harness pytest bundle passes after import.
- `git status --short --branch` returns only `## main` after the cache-disabled
  validation run.
- The evidence bundle remains present under
  `evidence/wordpress-skill-candidate-eval/`.

## Boundaries

This does not prove:

- public GitHub repo creation;
- maintainer approval of the metadata or clean-import strategy;
- live GitHub Actions execution;
- public artifact URLs for full result archives;
- long-run variance reduction;
- credentialed third-party AI-provider behavior.
