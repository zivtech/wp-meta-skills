# Package Build Record

The [current project status](docs/wordpress/project-status-current.md) records
the live repository state.

This tree was initially assembled from WordPress-specific content in the
`zivtech-meta-skills` monorepo and then hardened as the standalone
`zivtech/wp-meta-skills` repository. The clean public import, not the historical
package-generation process, is the current source.

## Current Build and Edit Path

Edit this repository directly. Distribution changes must update the applicable
skill and agent surfaces, regenerate `MANIFEST.sha256`, and pass the locked
validation sequence in [CONTRIBUTING.md](CONTRIBUTING.md). The Actions workflow
then checks the exact committed tree.

There is no supported command in this repository that reconstructs the package
from the former monorepo. Historical source locations and the clean-import
boundary are documented in [PROVENANCE.md](PROVENANCE.md).

## Non-Claims

The checksum manifest proves equality to its reviewed tracked inputs; it does
not sign or authenticate a release. A passing package build does not prove a
tag, GitHub Release, production deployment, or broad behavior of generated
WordPress code.
