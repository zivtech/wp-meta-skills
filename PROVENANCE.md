# Provenance

The [current project status](docs/wordpress/project-status-current.md) is the
stable state reference. This document describes historical origin and the
current ownership boundary.

## Historical Source Shape

The first standalone package was assembled from WordPress-specific areas of the
private `zivtech-meta-skills` monorepo:

- WordPress agents and skills;
- WordPress documentation and standalone metadata;
- WordPress evaluation suites and a pruned validation harness;
- shared validation scripts and the installer/manifest verifier;
- selected evidence later committed under the public `evidence/` tree.

The package moved the WordPress discovery surfaces to repository-root Claude
and Codex directories so installation no longer depended on the monorepo
layout.

## Public History Boundary

The public repository uses a clean-root import. Its first commit is
`6de8aa99ea8f7106cf1016b740abeb152791d53e` (`chore: initial public release`).
That boundary avoids representing the staging history as the public package's
complete path history.

This file does not claim that the clean import preserves per-file ancestry or
that the public evidence is byte-equivalent to private originals. The dated
packaging limitation is recorded in [EVIDENCE.md](EVIDENCE.md).

## Current Ownership

The standalone `zivtech/wp-meta-skills` repository is now authoritative. Its
skills, harness, evidence map, controls, and validation workflow are edited and
reviewed directly. The historical monorepo assembly process is not a supported
current build path.

## Reuse Boundary

Repository skill text is maintained as original Zivtech work. Reference-only
comparison with upstream projects is permitted; copied or closely adapted text
requires license review, source attribution, and a reuse-ledger entry before it
can land.

## Non-Claims

Provenance does not establish release signing, full source-history preservation,
public artifact immutability, production readiness, security assurance, model
superiority, or long-run variance reduction.
