# Deep Dive: Page-Builder → Blocks Migration Verifier - 2026-07-02

Target 3 from `docs/wordpress-assist-research-plan-2026-07-02.md`. Status:
research brief, not an approved spec. Claims marked [fetched] vs
[snippet-only]; local repo facts read directly.

Core finding: every conversion tool that exists (or existed) *asserts*
success; none proves it. Nelio Unlocker's cloud-service dependency is why it
left no successor when it closed 2025-04-24. A local, deterministic,
evidence-emitting **verifier** is both the wedge and the de-risked MVP — it
can certify any converter's output (AI, WebRitual, or a human rebuild) before
we build a converter at all.

## 1. Source-format anatomy

| Builder | Storage | Extractable w/o builder active? | Notes |
|---|---|---|---|
| **Elementor** (free 3.34.2, GPLv3, wp.org) | `_elementor_data` postmeta: JSON element tree `{id, elType: section\|column\|container\|widget, widgetType, settings, elements[]}` [fetched: [elementor-developers-docs](https://github.com/elementor/elementor-developers-docs) general-structure.md, widget-element.md] | Yes (`wp post meta get <ID> _elementor_data`) | Global kit styles live in a hidden `elementor_library` CPT post (`elementor_active_kit` option) — much of the "design" is not in the element tree; converter must merge kit defaults. Media as `{url, id}` (attachment IDs recoverable) |
| **WPBakery** (paid $64, v8.7.3) | Nested shortcodes in `post_content` (`[vc_row][vc_column]...`) | Yes (`get_shortcode_regex()`) | `vc_raw_html` stores **base64** content; `link` attrs use `url:...\|title:...` encoding; renders as literal text on deactivation |
| **Divi 4** (paid) | `[et_pb_*]` shortcodes + `_et_pb_old_content` backup meta; **global presets in `et_divi` options** — shortcode alone under-specifies appearance | Yes, but must snapshot options too | Divi 5 (2025) moved to JSON, one-time migration — Divi-4 sites are the stuck ones; extractor needs two parsers [snippet-only: elegantthemes.com Divi-5 posts] |
| **Beaver Builder** (Lite is GPL on wp.org) | `_fl_builder_data` postmeta: **serialized PHP** with stdClass nodes, flat parent-pointer structure | Yes but extract in-PHP only (`wp eval` + `wp_json_encode`) — never unserialize outside WP | Tree must be rebuilt from `parent`/`position` |
| **Oxygen ≤4** | `ct_builder_shortcodes` / `ct_builder_json` postmeta; ignores `post_content`, disables theme output — plugin off = **page renders nothing** | Yes (meta) | Hardest lock-in shape; Oxygen 6 rebuilt on Breakdance engine (JSON) |
| **Bricks** (paid theme) | `_bricks_page_content_2` postmeta JSON `{id, name, parent, children, settings}` | Yes | No official public schema [snippet-only: bricksbuilder forum] |

Start with Elementor: best-structured source, free, GPL, fixture-safe.
Only the **rendered baseline** (before-capture) needs the builder running.

## 2. Target-format mapping

Clean core mappings (WP 6.9): heading→`core/heading`; text/HTML→
`core/paragraph`/`core/list`/`core/quote` via split; image→`core/image`
(carry attachment ID); section/row/column→`core/columns`/`core/group`;
button→`core/buttons`; spacer→`core/spacer`; divider→`core/separator`;
video→`core/embed`; toggle/accordion→**`core/accordion` (new in 6.9)**
[snippet-only: kinsta.com/blog/wordpress-6-9, make.wordpress.org 6.9 field
guide].

Core gaps and the policy menu (planner must surface, executor must never
decide silently):

- **Tabs**: not in core → accordion restructure, approved third-party block
  (Kadence), or heading+content flatten.
- **Forms**: no core block → recreate in a form plugin + embed, or a visible
  TODO placeholder. Never fake a static form.
- **Sliders**: no core block → `core/gallery` flatten, third-party carousel,
  or static stack. (The only live free converter, WebRitual Block Bridge,
  hard-depends on Kadence for exactly these [snippet-only: wp.org page].)

Contract: every unmappable widget resolves to (a) allowlisted third-party
block, (b) static flatten with waiver, or (c) TODO placeholder — and all
three must appear in the evidence packet's `unmapped[]`.

Landscape: Nelio Unlocker built an intermediate tree sent to a **cloud**
transformation service (why it died with the company; local+deterministic is
the differentiation) [snippet-only: neliosoftware.com, wpmayor review].
WebRitual Block Bridge (~20 Elementor widgets, Kadence dependency, Pro
widgets manual); "Gutenberg AI" commercial converter (claims unverified);
Elementor's "Blocks for Gutenberg" deepens lock-in rather than converting;
10up Convert to Blocks is classic-content only and maintenance-mode
[fetched: README]. **Nobody ships a verifier.**

## 3. The verification core

**Gate A — block validity (blocking).**
A1 CLI round-trip via `wp eval`: walk `parse_blocks()` output — fail on any
null-blockName non-whitespace segment (`unparsed_content`), any block not in
`WP_Block_Type_Registry` outside the declared allowlist, unstable
`serialize_blocks(parse_blocks(x))` round-trip, any `core/freeform`, and
`core/html`/`core/shortcode` beyond a declared budget (default 0).
A2 editor validity: Playwright opens the converted post (reusing the
`--deprecation-smoke` machinery) and asserts every block reports
`isValid === true` via `wp.data.select('core/block-editor').getBlocks()`,
no recovery prompts, no console errors. A1 can't catch save/markup
mismatches; A2 can.

**Gate B — content preservation (blocking).**
Before: wp-env with builder active → Playwright loads permalink, kills
animations via injected CSS, extracts container-scoped `innerText`. After:
builder deactivated, converted post, same extraction. Normalize (NFC,
whitespace collapse, zero-width strip) → token-sequence diff. Any deletion
> N visible chars (N=0 for fixtures) = fail with the deleted span quoted.
Insertions are warnings (TODOs are legitimate, declared insertions).
Waiver list for builder UI artifacts ("Toggle", "Previous/Next"). Fallback
when a paid builder can't be provisioned: extract from the source data tree,
report `source: "data-tree"` — never silently equate the two.

**Gate C — media/link inventory (blocking).**
Union of before-DOM and data-tree: `img src`+`srcset`, `a href`,
`iframe/video/source src`, inline-style `background-image`, attachment IDs.
Normalize (absolute URLs, strip cache-busters, resolve `-300x200`
intermediates). Rule: after ⊇ before; every miss listed with source element
ID. Builder-CSS-only background images are the known hard case — inventory
from the data tree, require a cover-block equivalent or waiver.

**Gate D — structural sanity (blocking).**
Ordered heading outline `[(level, text)]` before/after: identical text
sequence; level changes only if declared in the mapping manifest. Compare
list/table/blockquote counts.

**Gate E — visual similarity (advisory, never blocking).**
Screenshots at 2 viewports, SSIM/pixelmatch score recorded. Must not block:
an honest conversion intentionally changes rendering (theme typography
replaces builder CSS); pixel thresholds are flaky; the score sorts the
human-review queue — Gates B-D are the loss detectors.

**Evidence packet** `conversion-verdict.json`
(`"schema": "wpms-conversion-verdict/v1"`) per post: source builder+version,
`source_hash`, converted draft ref, per-gate status objects, `unmapped[]`
with resolutions/waivers, verdict + `blocking_failures`, environment. Site
rollup: `{posts_total, pass, fail, blocked, needs_review[],
unmapped_widget_histogram, verdict}` — same pass/fail/blocked vocabulary as
the existing oracle stack.

## 4. Repo fit

The packet → materialize → static gate → certify → runtime smoke pipeline
fits with minimal deformation:

1. **Packet gate**: add `conversion` as a fourth executor kind
   (`validate_wordpress_executor_packet.py`, `PACKET_SECTIONS` in
   `materialize_wordpress_executor_packet.py`); packet carries
   `converted/post-<id>.html` files + `mapping-manifest.json` +
   `waivers.json` (suffixes already in `SAFE_SUFFIXES`).
2. **Static artifact gate**: new `--artifact-type block-content` in
   `validate_wordpress_artifact.py` — block-comment grammar sanity, no
   freeform blocks, manifest schema. Static ≠ runtime proof, per runbook
   doctrine.
3. **Runtime smoke**: new `--fixture-kind conversion` in
   `run_wordpress_runtime_smoke.py`: provision → activate pinned builder →
   import fixture (WXR / `wp post meta update <id> _elementor_data`) →
   BEFORE capture → write converted draft → deactivate builder → AFTER
   capture + Gates A-E → `conversion-verdict.json` + scorecard. Missing paid
   builder → `blocked`. Structural novelty: first fixture kind needing two
   renders of the same content in one wp-env session, and the first whose
   artifact is content, not code.
4. **Repair loop**: `orchestrate(generate_fn, certify_fn)` unchanged —
   `certify_fn` = the conversion gates; failing-gate JSON (deleted spans,
   missing URLs, invalid blocks) is the repair feedback. The migration
   planner's hard gates already anticipate this executor.

## 5. Conversion pipeline

Per post: extract (in-PHP, into a builder-agnostic intermediate tree
`{id, kind, text/html, media[], links[], children[], settings_residue{}}`)
→ map (deterministic rule table first, versioned in `mapping-manifest.json`;
AI handles only the residue and must emit waiver/TODO for anything unmapped)
→ serialize → gates → bounded repair loop, last-good preserved → verdict.

Batch: per-post verdicts + site rollup; site passes only if every in-scope
post is pass or explicitly waived; `blocked` never folds into pass. Review
queue ordered by visual score ascending.

Idempotency/rollback: never mutate the original. Converted markup goes to a
new draft carrying `_wpms_conversion_source = {post_id, source_hash}`
(same hash = idempotent skip). Cutover is a separate human-approved step
that swaps `post_content` and stashes the original in postmeta (Divi's
`_et_pb_old_content` is precedent), leaving builder meta intact — rollback =
restore stash. Only a post-verification cleanup pass deletes builder meta.

## 6. Skill surface

- **Planner**: extend `wordpress-planner.migration` (its hard gates already
  cover builder conversion) with a deterministic inventory tool: scan
  postmeta keys + shortcode tags → builders detected, widget-frequency
  histogram, per-template grouping, effort estimate, fixture candidates.
- **Executor**: new `wordpress-conversion-executor`: approved plan +
  extracted trees in; conversion packet out (converted files +
  mapping manifest + waivers + oracle handoff naming exact gate commands).
- **Critic**: new `wordpress-conversion-critic` (read-only): reviews what
  gates can't see — semantic loss (CTA prominence, meaning carried by
  color/layout, alt-text quality, responsiveness), waiver honesty, whether
  TODOs fit the site's editorial reality. Gates prove nothing
  textual/structural was lost; the critic judges whether what was preserved
  still means the same thing.

## 7. Fixture plan

- **(a) Elementor, ~10 widgets** (pin free 3.34.2 via
  `https://downloads.wordpress.org/plugin/elementor.3.34.2.zip` in
  `.wp-env.json`): heading, text-editor, image, button, spacer, divider,
  icon-list, accordion (→ `core/accordion`), video embed, two-column
  container. WXR + `_elementor_data` JSON + hand-authored answer key
  (expected blocks + expected inventory). Fully redistributable.
- **(b) WPBakery page with one no-clean-equivalent widget** (`vc_tta_tabs`):
  the shortcode fixture text is ours to author freely; the plugin runtime is
  the issue. Envato split-license nuance: WPBakery's PHP is GPL (stated
  since 2018) so redistribution is legally defensible, but assets may not
  be, and this repo's conservative reuse posture argues against bundling —
  so the fixture runs in the `blocked`-aware lane: BEFORE-render gate needs
  a locally licensed copy via flag (never committed); without it, gates fall
  back to data-tree extraction and the rendered-baseline gate reports
  `blocked`. Divi same treatment, deferred past V1.
- **(c) Classic-editor + shortcode post**: freeform HTML + `[gallery]`;
  shortcodes must become preserved `core/shortcode` blocks, not expanded or
  dropped. Comparator: 10up Convert to Blocks behavior [fetched README].
- **Gate self-test**: mutation-test the verifier on fixture (a) — seed known
  losses (drop a paragraph, swap an image URL, demote an h2); each gate must
  catch its seeded mutation before any converter is trusted.

## 8. Effort, risks, maintainer questions

**Phasing (verify-first):** P1 verifier gates + evidence packet + fixture (a)
with mutation tests — already a product on its own. P2 extractors + planner
inventory tool. P3 conversion executor + repair loop; fixtures (b), (c).
P4 critic, site rollup, review queue; paid-builder lane if licensed.

**Risks:** render-diff flakiness (fixture determinism, animation-kill CSS,
text-not-pixels blocking signal); builder version drift (pin versions,
record `builder_version` in packets, version the mapping manifest —
Elementor's sections→containers migration is the cautionary tale);
paid-builder licensing (blocked lane keeps evals honest); CPU cost (one env
per batch, batched before-captures); extraction edge cases (slashed JSON,
base64 `vc_raw_html`, serialized PHP via `wp eval` only). What gates can't
see — meaning carried by design — is permanently the critic's territory;
document it.

**Maintainer questions:**
1. Core-blocks-only target, or is a Kadence-class dependency acceptable?
   (Decides tabs/slider/form policy and fixture (b)'s honest answer.)
2. Will Zivtech buy WPBakery/Divi licenses for the fixture/CI lane, or do
   paid-builder gates stay permanently blocked-with-data-tree-fallback?
3. Does conversion enter as a fourth executor kind inside the certification
   stack, or ship as a standalone verifier CLI first? And is cutover ever in
   the executor's scope, or always human?
