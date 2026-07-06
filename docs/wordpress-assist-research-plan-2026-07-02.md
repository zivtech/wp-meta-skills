# WordPress Tech-Assist Research Plan - 2026-07-02

Question: where do WordPress developers and agencies hurt enough that a
"super genius" assistant with verification tooling provides real leverage, and
which of those areas should wp-meta-skills target next?

Method: five parallel research angles (agency surveys and sentiment; Gutenberg
DX and migrations; WooCommerce, headless, and multisite; maintenance
economics; the AI-in-WordPress landscape), roughly 60 searches and 90 candidate
claims. GitHub sources were fetched and read directly; most other hosts were
egress-blocked in the research environment, so survey statistics and pricing
figures are verified at search-snippet level only and are marked accordingly.
Re-verify specific numbers before quoting them in marketing.

## Headline finding: generators everywhere, verifiers nowhere

By mid-2026 the WordPress ecosystem is saturated with AI *generation*: Telex
generates blocks, Big Sky generates sites, Elementor/Divi AI generate layouts,
AI Engine and ClassifAI generate content, and core now ships the plumbing
(Abilities API in 6.9, AI Client in 7.0, MCP Adapter plugin). WordPress's own
`agent-skills` repo teaches assistants how to generate WordPress code — but
defines no output contracts and no acceptance oracles. Meanwhile the failure
mode is documented (hallucinated hooks, deprecated APIs, 40%+ of AI code with
security flaws per Endor Labs, SQL injection hidden behind PHPCS annotations),
and AI-scaled offense is real (a May 2026 pipeline reportedly found 300+
plugin zero-days in 72 hours at ~$20 each) while defense remains rule-based
virtual patching. Almost nobody ships verifiers. That is exactly the
planner → executor → critic + deterministic-gate shape this toolchain already
has.

## Ranked pain areas

Ranking = economic weight × evidence strength × verification leverage (how
much a deterministic gate changes the outcome).

| # | Pain area | Why it is hard | Frequency / weight | Gateable? | Existing AI coverage |
|---|---|---|---|---|---|
| 1 | Plugin/site update and conflict management | 20-30 plugins per site, combinatorial interactions, silent breakage; staging-tested updates are the explicit price gap between $50/mo and $140/mo care plans | Daily; the recurring-revenue backbone of agencies | **Strong**: wp-env pre/post-update activation smoke, fatal-log diff, critical-page render checks | Rollback products (WP Umbrella) are non-AI and proprietary; no open update-verdict oracle |
| 2 | Security review and vuln triage | 11,334 new ecosystem vulns in 2025 (+42% YoY, Patchstack), median ~5h to first exploitation, 46% unpatched at disclosure; dominant classes are escaping/nonce/capability mistakes | Triage daily; deep audits highest-rate work | **Partial**: WPCS sniffs, Plugin Check, PHPStan taint paths prove the mechanical layer; exploitability judgment stays with the critic | Patchstack/Wordfence detect and vPatch; no AI code-review critic with deterministic evidence |
| 3 | Page-builder → blocks migration | Shortcode lock-in (WPBakery/Divi render as plain text on deactivation); the only serious auto-converter (Nelio Unlocker) shut down April 2025; manual rebuilds run ~$1.5k-$8k+/site; enterprises are exiting builders over technical debt | Per-project, weeks-months, high ticket | **Excellent**: `parse_blocks()` round-trip validity, content-loss DOM/text diff, link/media reconciliation, editor-load check | Effectively none since Nelio died — the largest unowned category |
| 4 | WooCommerce transitions (HPOS, checkout blocks) | HPOS default since 8.2 breaks legacy `get_post_meta`/`WP_Query` order access; checkout blocks removed PHP hooks with no 1:1 path — most merchants still on shortcode checkout as of early 2026; template overrides go stale every major release | Daily for commerce agencies; every store, every monthly Woo release | **Strong**: legacy-API grep, wp-env + HPOS activation verify, compatibility-declaration checks, template `@version` diff, end-to-end checkout smoke | None; CodeWP's Woo mode was acquired and sunset |
| 5 | WordPress-correctness gating of AI-generated code | 57%+ agency AI adoption meets models that hallucinate hooks and suggest deprecated APIs; official agent-skills has guidance but no oracles; Telex ships unverified zips | Rapidly becoming daily — every AI-assisted commit | **Strong and cheap**: API-existence lint vs versioned symbol DB, deprecation lists, phpstan-wordpress, Plugin Check, wp-env activation | Ad-hoc practitioner setups only; no productized WordPress critic |
| 6 | Block deprecation/validation at scale | Core validation-strictness issue open since 2018; deprecation arrays "not realistic at scale"; stale attribute shapes persist in the DB indefinitely; editors see "invalid content" on client sites | Recurring for custom-block libraries; high severity | **Excellent**: historical-markup fixture tests vs deprecation array, parse/re-serialize round-trip, block.json schema, stale-attribute render fixtures | None — Telex generates, nothing tests deprecations |
| 7 | Legacy PHP 7.x → 8.x fleet migration | ~22-30% of sites on EOL PHP; breakage enumerable but scattered across inherited codebases; agencies run fleet-wide audit-then-fix sweeps | Bursty project work, high volume across fleets | **Most gateable of all**: PHPCompatibility/PHPCS, PHPStan ratchets, wp-env on target PHP | Static analyzers exist; no agentized audit→patch→verify loop |
| 8 | Performance / Core Web Vitals | WP mobile pass rate ~46% vs Duda ~85%; flat through 2025; LCP/asset-bloat driven, often architectural (the builder is the problem) | Weekly; productized at $200-$1,000+ | **Measurement fully deterministic** (Lighthouse CI, CrUX, autoload size, query counts); remediation resists automation | Rule-based optimizer plugins; no AI diagnostician with verified before/after evidence |
| 9 | Enterprise integrations and content modeling | Top enterprise blockers: integrations 47%, content modeling 42%, governance 39% (SoEWP 2025); scarcest expertise | Core of enterprise retainers, highest value | **Moderate**: REST/schema contract tests, CPT/taxonomy registration assertions, webhook round-trips | None WordPress-specific |
| 10 | Headless previews/auth and costing | WP Engine's own RFC concedes preview/auth DX is bad; Faust.js being rearchitected; TCO rivals paid headless CMS | Niche but expensive when wrong | **Good**: schema snapshots, authenticated preview queries, draft round-trips | HWP Toolkit actively maintained — ecosystem owner already tooling it |
| 11 | Block theme / theme.json / hybrid decisions | Official guidance walked back "theme.json for everything"; hybrid is the production-safe pattern; ~57% route around React blocks via ACF; WP 7.0 PHP-only blocks shrink the scaffolding half | Every new build; medium severity | **Good**: theme.json schema, template lint, editor-vs-frontend DOM/CSS parity snapshots | Partially covered by existing theme planner/critic; parity oracle missing |
| 12 | Multisite surgery (extraction, shared users) | Prefix/capability/serialized-URL conversion without corruption; one fatal downs the whole network | Rare, hazardous, episodic | **Good**: WP-CLI export/import round-trip with integrity checks | None |

## What this means for wp-meta-skills

Priority targets, in order — each pairs an assistant skill with a
deterministic gate the ecosystem lacks:

1. **Update-safety oracle** (#1): a wp-env replay harness that produces an
   evidence packet per update — activation, fatal-log diff, front-end render.
   Extends the existing runtime-smoke harness; daily-work economics.
2. **Builder→blocks migration verifier** (#3, with #6): AI does the fuzzy
   conversion, gates prove nothing was lost — block validity round-trip,
   content diff, media/link reconciliation. Biggest unowned category; natural
   extension of wordpress-planner.migration + a new conversion executor lane.
3. **WooCommerce transition gates** (#4): HPOS legacy-API scan +
   HPOS-enabled activation verify + checkout smoke; a "Woo transition critic".
4. **API-existence / deprecation lint** (#5, #6): versioned core+Woo symbol
   database as a certifier gate — directly serves the repo's stated exact-API
   improvement target and differentiates against WordPress/agent-skills.

Continuing as cross-cutting layers: the security critic (#2) — the single
best-evidenced expertise gap — and the performance critic (#8) with a
Lighthouse-CI-style before/after oracle added. Areas #9-#12 are real but
either partially owned upstream or too episodic to lead with.

## Deep dives

Each priority target now has a full build brief (pain anatomy → gate design →
skill surface → fixtures → effort/risks → maintainer questions):

- `docs/wordpress/deep-dive-update-safety-oracle-2026-07-02.md`
- `docs/wordpress/deep-dive-security-gate-triage-2026-07-02.md`
- `docs/wordpress/deep-dive-builder-to-blocks-verifier-2026-07-02.md`
- `docs/wordpress/deep-dive-woocommerce-transition-gates-2026-07-02.md`
- `docs/wordpress/deep-dive-api-existence-lint-2026-07-02.md`

## Validation plan (next research steps)

- For each priority target, build 2-3 focused fixtures in the existing eval
  style (known-broken update, known-lossy builder page, known-HPOS-breaking
  plugin) and prove the gate catches them deterministically before building
  the assistant-facing skill surface.
- Re-verify snippet-only statistics before external use: the $1.5k-$8k
  migration pricing (single source), the 57% ACF-blocks figure
  (vendor-adjacent), the 5-hour exploitation median (corroborated across two
  secondary sources, primary not fetched).
- Sanity-check demand against Zivtech's own client mix (e.g., multisite
  ranks last generally but jumps if the client base skews higher-ed/gov
  networks).

## Sources

GitHub sources were fetched directly (WordPress/gutenberg issues 7604, 12708,
29976, 47924, 61833; woocommerce/woocommerce #43010, #62266;
wpengine/faustjs#2140 and hwptoolkit; wp-graphql #3353; WordPress/abilities-api;
WordPress/mcp-adapter; WordPress/agent-skills; 10up/convert-to-blocks and
gutenberg-best-practices). Snippet-verified: Patchstack State of WordPress
Security 2025/2026, Melapress 2025 security survey, The Admin Bar 2025/2026
agency surveys, WP Engine AI Agency Trends (Apr 2026), State of Enterprise
WordPress 2025 (soewp.com via WebDevStudios), HTTP Archive CWV data via
Search Engine Journal and corewebvitals.io, Wordfence 2024 annual report,
wordpress.org/news and make.wordpress.org AI team posts, and the agency
posts cited inline in the table.
