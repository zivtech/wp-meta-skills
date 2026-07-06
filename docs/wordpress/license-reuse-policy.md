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

## Operational Rules

- Keep reference-only candidates out of production prompt wording.
- Record all adapted concepts, copied passages, or generated-from-upstream-docs material in `wordpress-skills/docs/reuse-ledger.md` before use.
- Record source repository or document URL, commit SHA or access date, license, local file path, reuse class, adapted section, and rationale.
- Do not make benchmark or superiority claims from uncalibrated single-judge scores.
- Do not move GPL-family prompt material into this monorepo merely because the future standalone repo may choose a compatible license.

## What This Does Not Claim

This is not a legal opinion. It is a repo-level operating policy that keeps V1 prompt maturation moving without entangling the monorepo in unresolved license choices.
