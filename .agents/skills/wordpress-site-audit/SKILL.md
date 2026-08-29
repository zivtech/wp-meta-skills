---
name: wordpress-site-audit
type: auditor
model: Codex-sonnet-4-6
description: Audit a running WordPress site from its public surfaces alone and report evidence-backed findings with an explicit ledger of what was never checked.
---

# WordPress Site Audit

## When to Use

Use when the subject is a running WordPress site rather than a repository, and the question is what it is built on and where it is weak. An auditor observes a system it does not control: it reads public surfaces, records the artifact behind every claim, and never changes the site. Run it before scoping a builder-to-blocks migration, a plugin-debt cleanup, or a platform move, and whenever a stack description was asserted rather than measured. For what an agent can run in a local development environment, use `wordpress-environment-probe` instead; that measures capability, this measures a deployed site.

## Protocol

Phase 0 - Scope and authorization: state the target URL, who authorized the audit, and the access tier, where tier 1 is unauthenticated public surfaces only and any higher tier requires credentials the site owner supplies through their own channel.
    Phase 1 - Canonical resolution: resolve the effective URL once before any other request and reuse it for every check, because a redirect makes a body match fail exactly as a non-WordPress site does.
    Phase 2 - Stack identity: cross-check the core version across the REST root, the generator tag, and asset version query strings, record disagreement as its own finding, and read host and CDN from response headers rather than from the marketing site.
    Phase 3 - Theme identity: read the theme header block for name and version, treat a Template line as proof of a child theme and a theme.json file as proof of a block theme, and record a custom theme with no update channel as maintenance exposure.
    Phase 4 - Plugin inventory: collect plugin slugs from asset paths and REST namespaces, note that this enumerates only plugins that emit a public surface, and never present the result as the installed plugin list.
    Phase 5 - Editor posture: detect the page builder in use, detect native block markup, and treat builder markup and block markup appearing together as a half-finished migration whose scope must be stated explicitly.
    Phase 6 - Version currency: compare each detected slug against the plugin directory API for current version and last-updated date, compare core against the core version-check API, and report a stale release date as abandonment exposure independent of any vulnerability.
    Phase 7 - Security surface: observe only, recording user enumeration behavior, exposed artifacts, directory listing, and login surface reachability by read requests alone, and never convert a version gap into a vulnerability claim without citing a named advisory.
    Phase 8 - Dependency and delivery survey: enumerate every external script, style, font, and frame host and test that each still resolves and serves, then record content scale from sitemaps, the registered content model from the REST type and taxonomy routes, any performance or accessibility measurement that actually ran, and whether translated content comes from a translation plugin or from a machine-translation widget, because machine-translated legal or policy text is a finding in its own right.
    Phase 9 - Report and handoff: compile findings with severity, root cause, and a quotable evidence artifact each, list every check that could not run at this tier, and name the authorization needed to raise the tier or the probe skill that takes over once code access exists.

## Hard Gates

- Observe, never exploit: issue only requests a normal browser or a documented public API would make, and never attempt login, submit credentials, test default passwords, fuzz, enumerate paths at volume, or send a write request to any endpoint including `xmlrpc.php`.
    - Rate-limit every sweep: issue requests sequentially with a pause between them, because this is production infrastructure belonging to someone else.
    - Stop on any block or throttle: record what was blocked, and never retry with a changed fingerprint to get around a `403` or a `429`.
    - Never claim a vulnerability from a version number: a version behind current is a currency finding stating detected version, current version, and release-date gap, and attaching a CVE requires naming the advisory source that was checked.
    - Never treat a detected version as the installed version when it came from a published `readme.txt`, because that file states what the directory ships rather than what the site runs.
    - Raising the access tier requires explicit authorization from the site owner, and credentials must arrive through the owner's own channel and never be requested in chat.
    - Record every check that did not run as `NOT CHECKED` rather than as a pass, because a disabled directory listing is not proof of hardening.
    - Never write a secret, key, salt, or credential into any audit artifact, and never modify the audited site.

## Exact API And Verification Contract

Name the concrete observed surface behind every claim instead of a category label: canonical resolution is proven by `curl -sIL "$URL" -o /dev/null -w "%{url_effective}"` and every later request reuses that resolved value with a browser user agent, core identity is cross-checked across the `/wp-json/` root, the `<meta name="generator">` tag, and `?ver=` query strings on `/wp-includes/` assets, theme identity comes from the `/wp-content/themes/<slug>/style.css` header block where a `Template:` line proves a child theme and a `theme.json` file proves a block theme, plugin identity comes from `/wp-content/plugins/<slug>/` asset paths plus the `namespaces` array of the REST root, per-plugin published versions come from the `Stable tag` line of `/wp-content/plugins/<slug>/readme.txt`, currency is measured against `https://api.wordpress.org/plugins/info/1.2/?action=plugin_information&request[slug]=<slug>` for `version` and `last_updated` and against `https://api.wordpress.org/core/version-check/1.7/` for core, content scale comes from `/wp-sitemap.xml` or `/sitemap_index.xml`, the registered content model comes from `/wp-json/wp/v2/types` and `/wp-json/wp/v2/taxonomies`, and every check that did not run is recorded as `NOT CHECKED`. If no exact WordPress API applies, state why and name the verification oracle instead.

## Calibration

Report; do not remediate, and do not propose the engagement. Detection is a fingerprint, not a confession: a plugin slug in an asset path proves that plugin emitted an asset, not that it is active, configured, or at fault. Prefer a named `NOT CHECKED` over an inferred pass, and prefer a quotable artifact the reader can fetch themselves over a summary they must trust. An audit is a snapshot of one origin at one moment; a cache, a CDN edge, or an optimizer plugin can each make the site you measured differ from the site a visitor gets, and saying so is part of the deliverable. Severity belongs to business consequence rather than to how unusual the finding looked.

## Failure Modes

Watch for reading an empty body match as absence of WordPress when the request was answered by a redirect, which is the defect that made an earlier live run report zero findings against a site that was in fact a builder site behind a CDN; trusting a generator tag that a plugin or a security header rewrote; concluding a plugin is absent because a minifier concatenated its assets out of the path namespace; reporting a published directory version as the running version; treating a disabled directory listing or a hidden login path as evidence of hardening; converting a release-date gap into a vulnerability claim with no advisory named; and presenting a public-surface plugin list as the site's true inventory.

## Output Contract

Use these headings:
- `## Access Tier And Authorization`
- `## Stack`
- `## Findings`
- `## Evidence`
- `## Not Checked`

Every finding names the artifact a reader can fetch to confirm it and the oracle that would settle it independently, such as a browser devtools network panel check, a crawl comparison, or Core Web Vitals field data. Each Not Checked entry states why the check could not run and what is therefore not claimed, so the ledger reads as scope rather than as silence.

## Provenance

Original Zivtech auditor protocol. Ported from an internal discovery-investigation draft with its proposal-workflow couplings removed, so this skill audits a site and stops there rather than driving a sales process. The tier-1 detection recipes were smoke-tested once on 2026-08-28 against a live site with independently known ground truth, a run that reproduced the CDN, custom theme, builder, and dead-dependency findings and also exposed the canonical-resolution defect now fixed in phase 1. Higher access tiers, the currency API calls, and the performance and accessibility paths are protocol rather than measured evidence.
