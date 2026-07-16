# Standalone Cutover Record

The [current project status](docs/wordpress/project-status-current.md) is the
active status source. This file records how the standalone repository boundary
was established and the rule that now governs edits.

## Completed Boundary

The WordPress collection was assembled from the earlier `zivtech-meta-skills`
monorepo, validated as a standalone tree, and imported into
[zivtech/wp-meta-skills](https://github.com/zivtech/wp-meta-skills) with a clean
root. The initial public commit is
`6de8aa99ea8f7106cf1016b740abeb152791d53e`.

The clean import intentionally did not publish the staging repository's full
history. [PROVENANCE.md](PROVENANCE.md) describes the historical inputs without
claiming a path-preserving migration.

## Active Source-of-Truth Rule

`zivtech/wp-meta-skills` is the source of truth for this package. Make WordPress
skill, harness, documentation, workflow, and distribution-surface changes here.
Do not regenerate or overwrite the repository from the historical monorepo
package path.

Any downstream mirror or vendor copy must identify its source commit and prove
parity against this repository. A mirror being current does not make it an
authoritative edit surface.

## Validation and Publication Separation

Local and hosted gates prove only their named contracts. Repository visibility,
skills.sh discovery, a successful workflow, and a future tag are distinct
states. None alone establishes production readiness, security assurance,
benchmark superiority, or immutable artifact provenance.

If the source-of-truth architecture changes, amend this record and the current
status through a reviewed change before moving work. Do not silently resume the
old generation path.
