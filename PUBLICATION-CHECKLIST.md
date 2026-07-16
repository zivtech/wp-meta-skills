# Publication Record and Release Checklist

The [current project status](docs/wordpress/project-status-current.md) is the
stable entry point for repository state. This document records the clean public
cutover and keeps a separate checklist for any future tagged release.

## Public State Observed 2026-07-15

- Repository: [zivtech/wp-meta-skills](https://github.com/zivtech/wp-meta-skills),
  visibility `PUBLIC`.
- Initial public import: commit `6de8aa99ea8f7106cf1016b740abeb152791d53e`.
- Publication approval issue:
  [#1](https://github.com/zivtech/wp-meta-skills/issues/1), closed.
- Latest successful `validate.yml` push on `main` observed that day:
  [run 28811640050](https://github.com/zivtech/wp-meta-skills/actions/runs/28811640050)
  at `e0ebf6a3bee38fa3477e835c45325d078adde6fa`.
- Discovery page:
  [skills.sh/zivtech/wp-meta-skills](https://www.skills.sh/zivtech/wp-meta-skills),
  HTTP 200 and listing 14 skills when observed.
- Formal release state: no Git tags and no GitHub Releases were present.

These are dated external observations, not assertions enforced by the local
documentation validator. The public repository and skills directory listing do
not imply a semantic version, immutable release artifact, production support
commitment, or benchmark approval.

## Controls Completed for the Public Cutover

- Clean-root history was used instead of publishing the staging history.
- GPL-3.0 licensing, trademark language, security-reporting instructions, and
  provenance boundaries are present.
- Distribution parity and the checksum manifest bind the shipped skill and
  agent surfaces.
- The public Actions workflow exercises the locked general partition plus the
  separate no-secrets Linux Docker partitions.
- Public evidence is limited to tracked artifacts under `evidence/` and is
  mapped in [EVIDENCE.md](EVIDENCE.md).
- Active work is performed directly in this standalone repository; the former
  monorepo generation path is historical provenance.

## Checklist for a Future Tagged Release

Before creating a tag or GitHub Release:

- [ ] Choose and document the version and intended compatibility boundary.
- [ ] Confirm the current status pointer names the reviewed release candidate.
- [ ] Run the exact locked validation sequence in [CONTRIBUTING.md](CONTRIBUTING.md).
- [ ] Require successful general, sandbox-feasibility, and generated-runtime
      jobs for the exact candidate commit.
- [ ] Review the distribution parity and `MANIFEST.sha256` diffs.
- [ ] Scan the candidate diff and repository history for credentials, private
      paths, client data, and unrelated project content.
- [ ] Confirm every public evidence link resolves to a tracked artifact and
      every claim retains its `Not proven` boundary.
- [ ] Review dependency, image-digest, license, and provenance changes.
- [ ] Confirm the security-reporting route is enabled and usable.
- [ ] Create an annotated tag only after the exact commit has passed review.
- [ ] If publishing a GitHub Release, attach only artifacts built from and
      verified against that tag.
- [ ] Recheck the skills.sh page after publication without treating telemetry
      or listing presence as code-quality evidence.

## Rollback Rule

Do not rewrite public history to hide a failed release attempt. Revert the
specific release-facing change or publish a follow-up correction, preserve the
failed and passing CI links, and narrow claims to the evidence that remains.
