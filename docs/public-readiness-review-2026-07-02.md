# Public Readiness Review - 2026-07-02

Scope: full review of the `zivtech/wp-meta-skills` staging repositorysitory
before flipping visibility to public, including the name check and license
check, a repo-wide leak/reference sweep, and a re-run of every locally runnable
publication gate. Fixes applied during this review live on the same branch as
this document.

## Verdict

**Publishable after one remaining decision: the git-history strategy.** The
working tree is clean (no secrets, no copied third-party text, license posture
consistent, name cleared), all runnable gates pass, and the mechanical
pre-release fixes from `PUBLICATION-CHECKLIST.md` are now done. The one thing
that must not happen is flipping this staging repo public with its current
41-commit history, because redacted content still exists in earlier commits
(details below). Everything else on the checklist is owner sign-off, not work.

Making the repo public quietly before marketing is compatible with this state:
publish first, tag/announce later after the post-review CI run passes.

## Name Check

Researched 2026-07-02 (web search; WordPress Foundation trademark policy
reconstructed from policy snippets and secondary sources because direct fetch
was proxy-blocked).

- **Repo slug `wp-meta-skills`: keep.** No exact collision exists on GitHub,
  npm, Packagist, or WordPress.org. "WP" is explicitly outside the WordPress
  Foundation trademarks (post-2024 policy adds only "don't use it in a way
  that confuses people"), and the official `WordPress/agent-skills` project
  itself prefixes skills `wp-*`, so the convention reads as normal community
  usage. The `meta-` element is genuinely distinctive in a crowded namespace.
- **README title "WordPress Skills": changed to "WP Meta Skills".** The old
  title had three problems: (1) it used the full "WordPress" mark *as* the
  product name, which is the pattern the trademark policy's product-name
  clause prohibits ("cannot use them as part of a product, project, service,
  domain name, or company name" — descriptive "for WordPress" phrasing is the
  sanctioned alternative); (2) `jorgerosal/wordpress-skills` already exists
  with that exact name in the same category (Claude skills for WordPress);
  (3) the official `WordPress/agent-skills` (announced on wordpress.org/news
  January 2026) owns the "WordPress + skills" mindshare, and a commercial
  agency title reading as official invites exactly the confusion the
  Foundation now polices. README now uses the slug-matching title plus a
  "for WordPress" tagline and an explicit non-affiliation line.
- **Adjacent namespace to be aware of when marketing:** official
  `WordPress/agent-skills` (GPL-2.0-or-later), `Automattic/agent-skills`
  (MIT, archived into the WordPress org), community repos
  `elvismdev/claude-wordpress-skills` (MIT, ~210 stars) and
  `jorgerosal/wordpress-skills` (MIT), and the commercial "WP Skills" code
  generator at wp-skills.com. Positioning should lead with the differentiator
  none of them have: deterministic verification gates and the repair loop.

## License Check

> **Superseded 2026-07-03:** the maintainer approved and executed a
> relicense to **GPL-3.0** before first public release (see
> `docs/wordpress/verification-targets-decisions-2026-07-02.md`, item 2).
> The analysis below stands as the record of why Apache-2.0 was *viable*;
> GPL-3.0 was chosen for community-signaling reasons ("FOSS marketing, not a
> licensing play") and because it simplifies future GPL-data vendoring.
> All content is original Zivtech work, so the relicense affected no
> third-party grants.

- **Root license: Apache-2.0, keep.** It matches the `anthropics/skills`
  convention this audience knows. Nothing in the repo links against, includes,
  or derives from GPL WordPress code, so no GPL obligation attaches to the
  package itself. Precedent supports non-GPL WordPress tooling: WP-CLI is MIT,
  and Automattic published its own agent skills under MIT. The GPL expectation
  attaches at the WordPress.org plugin/theme directories, which this repo
  never enters.
- **Apache-2.0 vs GPLv2 nuance, handled:** Apache-2.0 is incompatible with
  GPLv2-only but compatible with GPLv3, and WordPress is GPLv2-or-later, so
  even a combined work resolves cleanly under GPLv3. To close the one
  theoretical wrinkle — a claim that Apache terms flow into code the executors
  generate for users — the README now states that generated artifacts are not
  derivatives of this repository and users may license them as they choose,
  including GPLv2-or-later for WordPress.org distribution.
- **Provenance verified clean.** `docs/wordpress/reuse-ledger.md` records all
  four upstream comparators (including GPL-2.0-or-later
  `WordPress/agent-skills`) as reference-only; a text sweep found no copied or
  closely adapted upstream passages anywhere in the skill prompts. The
  candidate catalog records commit SHAs and licenses per upstream.
- **Stale policy language reconciled.** `license-reuse-policy.md`,
  `provenance-policy.md`, and `CLAUDE.md` were written when the monorepo had
  no root LICENSE and said license handling was "not standardized" — factually
  wrong in this repo. Dated standalone-status notes now state the Apache-2.0
  decision while keeping the conservative no-copied-text rule as the operating
  policy by choice.
- **Minor, non-blocking:** 13 of 14 `SKILL.md` files carry only the generic
  provenance line rather than naming their compatible references (the policy
  in `CLAUDE.md` says they should). The central reuse ledger covers the
  requirement; tightening per-skill lists can be post-release hygiene.

## Leak Sweep (599 files)

- **Secrets/credentials: clean.** No API keys, tokens, private endpoints, or
  real client data. The only literal-assignment matches remain the documented
  `<anthropic-api-key>` placeholder and the standard `wp-env` test password.
- **Fixed on this branch — personal-path leak.** 15 tracked files contained
  `/Users/<local-username>/...` local paths, and 6 evidence stderr logs
  additionally leaked an unrelated local Codex plugin name from the author's
  machine. All were redacted (`/Users/redacted/...`,
  `/path/to/zivtech-meta-skills`, `redacted-unrelated-local-plugin`) without
  changing any scores, verdicts, or gate results; EVIDENCE.md now carries a
  dated redaction note. (This document originally quoted the leaked strings
  verbatim while describing the fix; they were re-redacted on 2026-07-02 so
  the tree stays clean for the history reimport.)
- **Fixed on this branch — placeholders and broken references.** SECURITY.md
  now points to GitHub private vulnerability reporting instead of the private
  Zivtech channel placeholder; CLAUDE.md (8 links) and AGENTS.md (5 links)
  now use the real `docs/wordpress/` paths; the README's self-flagged
  path-mismatch footnote is resolved and removed; CONTRIBUTING.md no longer
  instructs contributors to run a build script that only exists in the private
  monorepo; `evals/suites/QUALITY_GAPS.md` no longer quarantines two suites
  that are not in this repo.
- **Accepted as-is (historical provenance):** references to the private
  `zivtech-meta-skills` monorepo, monorepo `evals/results/` paths, PR #11, and
  approval issue #1 in PROVENANCE.md, EVIDENCE.md, and dated docs. These are
  honest provenance statements about where evidence came from; EVIDENCE.md
  already frames the full archives as out of scope unless published. The
  candid internal self-assessments ("no measurable edge over a strong few-shot
  prompt", "n=1 fixture") are consistent with the README's public claims
  boundary and are a credibility asset, not a leak.

## Gate Status (PUBLICATION-CHECKLIST.md)

Verified passing locally on this branch, 2026-07-02, after all fixes and a
manifest regeneration: `./install.sh --verify`;
`validate-agent-frontmatter.py` (14 agents);
`validate-wordpress-exact-api-contract.py`; strict eval-suite integrity for
all seven wordpress suites; the 14-file harness pytest bundle (148 passed).
Live `Validate wp-meta-skills` Actions are green on `main` at `14d906d`.

Remaining before visibility flip:

1. **History strategy (the real blocker).** The redactions fix the tree, not
   history: the personal paths shipped in the initial clean import commit
   `8798b2e` and the unrelated-plugin stderr files entered at `c93851c`. Making
   this repo public as-is publishes all 41 staging commits including the
   unredacted content. Two clean options, either satisfying the
   PROVENANCE.md clean-import strategy: (a) squash-reimport — create a fresh
   root commit from the current scrubbed tree (simplest, and exactly what
   PROVENANCE.md prescribed for the first public draft); or (b) rewrite with
   `git filter-repo` replacing the leaked strings throughout history. Do one
   of these, re-run CI, then flip visibility.
2. **Enable GitHub private vulnerability reporting** in repo settings
   (Settings → Code security) so the new SECURITY.md path works the moment the
   repo is public.
3. **Owner sign-offs tracked in issue #1:** metadata review, evidence
   boundaries (full archives stay out of scope for the first draft — already
   the documented default), cutover plan, and acceptance of the high-risk eval
   maturation gaps as post-release work.
4. **After the flip:** confirm live Actions pass on the public repo, then tag.
   Publishing quietly before any announcement is fine; the tag/announcement is
   the step PUBLICATION-CHECKLIST.md holds until post-review CI passes.

## Fixes Applied On This Branch

- Redacted personal paths and the unrelated plugin name in 15 evidence/docs
  files; added the EVIDENCE.md redaction note.
- Retitled README to "WP Meta Skills"; added the naming/affiliation/license
  section (non-affiliation + generated-code ownership note).
- Replaced the SECURITY.md private-channel placeholder with the GitHub
  private vulnerability reporting process.
- Repointed CLAUDE.md and AGENTS.md doc links to `docs/wordpress/`; removed
  the README reconciliation footnote.
- Added dated standalone-status notes to `license-reuse-policy.md` and
  `provenance-policy.md`; updated the CLAUDE.md reuse-policy section to state
  the Apache-2.0 decision.
- Corrected CONTRIBUTING.md validation instructions for the standalone layout.
- Removed stale non-existent-suite entries from `evals/suites/QUALITY_GAPS.md`.
- Regenerated `MANIFEST.sha256`; re-ran the full validation bundle (all pass).

## Non-Claims

This review does not approve public visibility (owner decision in issue #1),
does not add any new performance or superiority claims, and does not change
the evidence boundaries in EVIDENCE.md. The name and trademark assessment is
research-backed operating guidance, not legal advice.
