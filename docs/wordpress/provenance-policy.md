# WordPress Skills Provenance Policy

GPL-compatible reuse is allowed for this collection, but it must be tracked. The policy is designed to avoid dead output, accidental relicensing surprises, and unattributed upstream dependency.

## Reuse Classes

| Class | Definition | Required Documentation |
|---|---|---|
| Reference only | Upstream skill informs coverage or eval rubric, but no text is copied or closely paraphrased | Skill-level provenance note naming source repo and domain |
| Adapted concept | A workflow shape or checklist is translated into Zivtech protocol language | Source URL, commit SHA, license, adapted concept, local rationale |
| Copied passage | Upstream wording is reused substantially | Source URL, commit SHA, license, copied passage location, local file location |
| Generated from upstream docs | A new prompt is generated from upstream documentation rather than a skill file | Source doc URL, date accessed, license if known, generation note |

## Required Metadata

Every reused or adapted upstream item must record:

- source repository or document URL
- commit SHA or access date
- license
- local file path
- reuse class
- rationale

Use `wordpress-skills/docs/reuse-ledger.md` for durable entries. The active in-repo license decision is in `wordpress-skills/docs/license-reuse-policy.md`.

## Active License Decision

> **Standalone status (2026-07-02, license updated 2026-07-03):** the
> standalone `wp-meta-skills` repository has a root **GPL-3.0** `LICENSE`
> (relicensed from Apache-2.0 on 2026-07-03, before first public release).
> The block on copied or closely adapted third-party prompt text remains the
> operating policy here by choice; any future direct adaptation requires a
> license-compatibility check against GPL-3.0 plus a `reuse-ledger.md` entry.

Direct copied or closely adapted third-party prompt text is blocked inside `zivtech-meta-skills` for WordPress V1 until the root repository license is standardized. Upstream projects may be used as reference-only comparators and eval candidates.

| License | Current in-repo handling |
|---|---|
| GPL-2.0-only | Reference/eval comparator only |
| GPL-2.0-or-later | Reference/eval comparator only |
| MIT | Reference/eval comparator by default; direct adaptation requires a root license decision and ledger entry |
| Apache-2.0 | Reference/eval comparator by default; direct adaptation requires a root license decision and ledger entry |
| CC-BY | Reference/eval comparator by default; direct reuse blocked until attribution and compatibility are resolved |
| Unknown/no standard license | Reference/eval comparator only |

## Hard Gates

- Do not copy upstream skill text into a V1 prompt without a ledger entry.
- Do not copy or closely adapt upstream skill text into the monorepo while the active license decision blocks direct reuse.
- Do not mix license assumptions: WordPress/agent-skills is GPL-2.0-or-later by its LICENSE file even though GitHub reports `NOASSERTION`.
- Do not include secrets, real client data, production URLs, or credentials in fixtures, blueprints, or examples.
- Do not claim formal benchmark superiority from the current WordPress V1 candidate suite. The 2026-06-20 evidence closes the frontier-model review-quality arc as directional-internal only; reopen only for a changed measurement target with a fresh preregistered design.
