# WordPress Skills License And Reuse Policy

Updated: 2026-06-16. Standalone status note added 2026-07-02.

> **Standalone status (2026-07-02, license updated 2026-07-03):** this
> document was written inside the `zivtech-meta-skills` monorepo, before that
> repository had a root `LICENSE` file. The standalone `wp-meta-skills`
> repository you are reading has a root **GPL-3.0** `LICENSE` (relicensed
> from Apache-2.0 on 2026-07-03, before first public release; all content is
> original Zivtech work). The conservative rule below — no copied or closely
> adapted third-party prompt text; upstream projects are reference-only
> comparators logged in `reuse-ledger.md` — remains the operating policy here
> by choice. Any future direct adaptation of third-party text requires an
> explicit license-compatibility check against GPL-3.0 (GPL-family and
> permissive sources qualify) plus a reuse-ledger entry.

This policy governs WordPress V1 work in the standalone `wp-meta-skills` repository and preserves the clean-room operating rule chosen during the earlier `zivtech-meta-skills` phase.

## Current Decision

Direct copied or closely adapted third-party prompt text is blocked inside this monorepo for WordPress V1. The WordPress suite may use upstream projects as reference-only comparators, eval candidates, and coverage prompts, but the production skill prompts must remain clean-room Zivtech text unless a future license decision explicitly changes this rule.

This remains intentionally conservative even after the standalone GPL-3.0 relicense: compatibility now permits more reuse, but V1 production skill prompts still stay clean-room unless a future change explicitly records direct adaptation in the reuse ledger.

## License Matrix

| Upstream license | In-repo V1 handling | Standalone `wp-meta-skills` handling |
|---|---|---|
| GPL-2.0-only | Reference/eval comparator only. Do not copy or closely adapt prompt passages into this repo. | Allowed only if the standalone repo is explicitly GPL-2.0-compatible and attribution/provenance is logged. |
| GPL-2.0-or-later | Reference/eval comparator only. Do not copy or closely adapt prompt passages into this repo. | Allowed only if the standalone repo is explicitly GPL-compatible and attribution/provenance is logged. |
| MIT | Reference/eval comparator by default. Direct adaptation requires a root license decision plus reuse-ledger entry. | May be adapted with notice, source commit, local file, adapted section, and rationale. |
| Apache-2.0 | Reference/eval comparator by default. Direct adaptation requires a root license decision plus reuse-ledger entry. | May be adapted with notice, source commit, local file, adapted section, and rationale. |
| CC-BY | Reference/eval comparator by default. Direct reuse is blocked unless attribution, notice placement, and compatibility are explicitly resolved. | May be adapted only with attribution mechanics documented before release. |
| Unknown/no standard license | Reference/eval comparator only. Do not copy or closely adapt. | Same until license is verified. |

### Weak License Evidence (added 2026-08-28)

The `Unknown/no standard license` row above was written as if "unknown" were one
condition. A survey of non-skill sources on 2026-08-28 found three distinct
shapes of weak evidence, none of which is a LICENSE file, and all of which
resolve to that same conservative row:

| Evidence shape | Example | Handling |
|---|---|---|
| A package manifest declares a license, but the repository ships no LICENSE file | `license` field in `package.json` or `composer.json` | Unknown. A manifest field is a declaration by one contributor in one file, not a license grant. |
| A project website or documentation site states a license, but the repository ships no LICENSE file | A footer line on a docs site | Unknown. The site and the code can diverge, and the site is not part of the distribution. |
| A LICENSE file exists but its text does not match a known license, so classifiers report `NOASSERTION` | Standard license terms under a custom preamble | Unknown **until read and classified by a person.** The terms may well be permissive; the point is that nobody has checked. |

Record the evidence shape alongside the verdict, not just the word "unknown", so
a later reader can tell a missing file from an unread one — those need different
work to resolve.

**This is deliberately stricter than the stated labels.** A repository whose
`package.json` says `GPL-2.0-or-later` is probably GPL-2.0-or-later. Treating it
as unknown costs nothing while the source is reference-only, and the cost only
arrives if someone wants to adapt its text — which is exactly when the question
deserves a real answer rather than an inherited assumption.

## Operational Rules

- Keep reference-only candidates out of production prompt wording.
- Record all adapted concepts, copied passages, or generated-from-upstream-docs material in `wordpress-skills/docs/reuse-ledger.md` before use.
- Record source repository or document URL, commit SHA or access date, license, local file path, reuse class, adapted section, and rationale.
- Do not make benchmark or superiority claims from uncalibrated single-judge scores.
- Do not move GPL-family prompt material into this monorepo merely because the future standalone repo may choose a compatible license.

## What This Does Not Claim

This is not a legal opinion. It is a repo-level operating policy that keeps V1 prompt maturation moving without entangling the monorepo in unresolved license choices.
