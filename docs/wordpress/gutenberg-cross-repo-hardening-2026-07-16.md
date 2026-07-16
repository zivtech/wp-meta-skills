# Gutenberg Cross-Repo Hardening Plan — 2026-07-16

Status: draft v1 for independent critic review. This section records the
pre-critique plan; the approved revision will be appended rather than silently
rewriting the first proposal.

## Goal And Boundaries

Make Gutenberg claims in these repositories specific, mechanically enforced,
and backed by the strongest applicable oracle:

- `/Users/AlexUA_1/claude/wp-meta-skills`
- `/Users/AlexUA_1/claude/ai-initiative-modules/contentful_migration_wp`
- `/Users/AlexUA_1/claude/wp-drupal-ai-migration/drupal-to-wp-ai-migration`

The work distinguishes two related but different products:

1. custom-block planning, generation, static certification, and isolated
   WordPress runtime proof in `wp-meta-skills`; and
2. migration-produced serialized `post_content`, including core blocks and
   repository-owned dynamic blocks, in the two migration runtimes.

This plan does not claim production cutover readiness, real NTSS/NASA source
proof, cross-browser coverage, arbitrary HTML fidelity, WordPress VIP platform
approval, or a completed page-builder-to-blocks verifier. Historical
Interactivity API and deprecation results remain historical unless the current
isolated runtime supports and re-proves them.

## Current-State Evidence

### wp-meta-skills

- Clean starting tree at `bbafaf62b4742fc02445ab88924b2d91ed77bfdd`;
  completed Plans 006–019 are ledgered, but the former branch upstream is gone.
- Focused block-tool baseline: 210 tests passed in the primary audit; an
  independent audit passed 233 focused tests plus distribution, exact-API, and
  strict suite-integrity checks.
- The skill prose is materially stronger than its deterministic enforcement.
  A block-planner response using unrelated WordPress APIs can pass the generic
  output oracle.
- The static block artifact gate accepts malformed block names, missing local
  `file:` assets, and unrelated package scripts as registration/build evidence.
- Suite documentation and materializable examples advertise runtime commands
  that contradict the current direct-artifact identity, digest, assertion, and
  isolated-runtime requirements.
- The one executor repair fixture has no `runtime_assertions`, so the current
  repair lane cannot use the implemented block-runtime adapter.

### contentful_migration_wp

- Clean `main` at `cb17fbc`, tracking `origin/main`.
- Composer could not run initially because dependencies are not installed;
  syntax/JSON checks pass, and the repo has a substantive historical wp-env and
  Playwright gate stack.
- The golden Contentful Rich Text fixture uses direct text children where the
  canonical Contentful shape nests paragraphs under quotes/table cells and
  block children under list items. The renderer consequently emits nested or
  malformed Gutenberg markup for canonical inputs that the current fixture
  never exercises.
- Custom-block attributes are inserted into HTML comments with raw
  `json_encode()`. A value containing `-->` terminates the block comment rather
  than following WordPress `serialize_block_attributes()` semantics.
- `ContentVerifier` silently succeeds if block APIs are unavailable, permits
  zero checked posts, and conflates parse/serialize identity with editor
  validity.
- The editor gate saves/reloads but does not mutate and restore a block, so the
  public word “editable” is not independently exercised.

### drupal-to-wp-ai-migration

- Starting branch `wave-6-admin-ui` at `eee0539`; twelve pre-existing modified
  `proof/wave-2-5/*` files are user-owned and must not be overwritten or staged.
- Baseline `composer test` passes with 220 tests / 804 assertions. The audit
  also passed `composer smoke` 48/48 and PHPStan.
- Direct probes prove that scripts, iframes, event-handler attributes, and a
  top-level executable anchor can bypass the converter's fallback-only
  sanitizer and reach generated `post_content` with no drop record.
- The semantic oracle names text, links, image identity/alt/caption, list
  cardinality, and unsafe-link behavior; the verifier enforces only block names
  and canonical parser stabilization.
- The editor gate does not save/reload despite a byte-stability claim.
- Pass B ignores `wp_update_post()` failures and rewrites unchanged body bytes;
  the idempotence fingerprint cannot see content, revisions, or modified times.

## Draft V1 Implementation Plan

### Phase 1 — Make wp-meta-skills claims and deterministic gates agree

1. Tighten the block-planner output oracle so a pass requires evidence of:
   block classification; `block.json`; attributes and saved-markup decisions;
   `save()` versus `render.php`/`render_callback`; compatibility or deprecation
   treatment; and separate editor/frontend verification.
2. Tighten both block artifact scan paths:
   - require `block.json.name` to match a WordPress namespace/name grammar;
   - validate relevant metadata field types;
   - require each local `file:` metadata edge to resolve inside the artifact;
   - accept concrete `register_block_type()` evidence or an actual `build`
     script, not any package script.
3. Add negative regression tests for unrelated WordPress planner prose,
   malformed names, missing local assets, and lint/test-only scripts.
4. Replace every current-facing generated-block runtime example with the
   canonical direct-artifact command: exact artifact digest, evidence ID,
   block name, selector, text, build, full profile, strict profile, isolated
   runtime, write path, run ID, and timeout.
5. Mark external generated-block Interactivity/deprecation paths
   historical-only until implemented in the isolated artifact runtime.
6. Give the tracked block executor fixture exact `runtime_assertions` matching
   the materializable runtime-card packet and validate that it becomes
   runtime-eligible before provider invocation.
7. Update both `.agents/skills` and `.claude/skills` contracts. The block
   planner must route bulk migrated `post_content` through the migration
   planner/plugin executor while still owning custom-block metadata and saved
   markup. The migration planner must require semantic block oracles, unparsed
   content detection, editor save/reload, and frontend evidence.

### Phase 2 — Correct Contentful serialization and canonical source handling

1. Install the locked Composer and npm dependencies without changing lockfiles.
2. Add failing tests and update the golden fixture to canonical Contentful AST
   nesting for list items, quotes, table cells, table header cells, and a nested
   list.
3. Make `RichTextRenderer` container-aware:
   - top-level blocks emit block comments;
   - list-item content emits valid `core/list-item` structure;
   - quote paragraphs remain valid nested quote content;
   - table cells flatten their allowed paragraph children into table-cell HTML;
   - unsupported container children produce an explicit warning rather than
     malformed nested markup.
4. Replace raw block-comment JSON with `serialize_block_attributes()` when
   WordPress is available and an exact compatible fallback otherwise. Test
   `-->`, `<!--`, `<`, `>`, `&`, quotes, backslashes, Unicode, and multiline
   content. A live WordPress smoke must parse exactly one custom block and
   recover the original attributes with no freeform residue.
5. Extract a testable Gutenberg content inspector used by `ContentVerifier`.
   Report block API availability, non-whitespace freeform segments,
   parse/serialize equality, registered block names, placeholder leakage, and
   checked-post count separately. Zero checked posts and unavailable block APIs
   fail closed; editor validity remains explicitly a separate Playwright gate.
6. Extend the editor smoke to mutate one core paragraph, save/reload, verify the
   mutation, restore the original, save/reload, and verify restoration before
   the frontend gate runs.
7. Correct README/mapping/checklist claims only after focused PHPUnit, the full
   suite, lint, product gates, frontend proof, classic-theme proof, and cleanup
   pass.

### Phase 3 — Close Drupal converter, oracle, and write-path false greens

1. Add RED tests for hostile descendants in paragraphs, headings, and lists;
   hostile attributes in every supported branch; top-level executable anchors;
   mixed benign/hostile content; and exact single drop records.
2. Sanitize the whole parsed body subtree and process anchors once before block
   dispatch. Remove fallback-only/per-node duplication so every supported
   branch shares one enforcement path and report rows are not duplicated.
3. Make body writes fail closed and byte-idempotent:
   - require the mapped `WP_Post` to exist;
   - skip `wp_update_post()` when generated bytes equal stored bytes;
   - otherwise call `wp_update_post($args, true)`;
   - throw on `WP_Error` or zero.
4. Extend source-link mapping to known aliases as well as `/node/{id}` so the
   declared record-105 destination link is enforceable.
5. Make every currently declared block-oracle property executable: text,
   expected href, image attachment/alt/caption, list-item count, and unsafe-link
   visible-text/executable-href behavior. Add mutation tests proving each
   property can independently fail.
6. Make the editor gate save and reload, record before/after serialized-content
   hashes, assert equality, and retain recursive invalid-block and console
   checks. Run it against every oracle-backed post or narrow the documented
   coverage to the exact post tested.
7. Add a durable `docs/gutenberg-contract.md` defining supported source shapes,
   mapping, sanitization, link rewriting, unsupported/loss accounting,
   idempotence, version floors, and proof tiers.
8. Write new runtime evidence only under ignored `var/`; never overwrite the
   pre-existing dirty `proof/wave-2-5` artifacts.

### Phase 4 — Cross-repo validation and claim reconciliation

1. Run scoped host gates after each repository's implementation, then the full
   repository-native gate stack.
2. Run the `wp-meta-skills` block packet → materialize → tightened static
   artifact → isolated build/editor/frontend profile on the exact tracked
   fixture.
3. Run Contentful's PHPUnit/lint plus disposable wp-env product, browser,
   classic-theme, unresolved-reference, and cleanup gates.
4. Run Drupal's PHPUnit/smoke/PHPStan plus product gates into a new ignored
   output directory and the vertical smoke against the local VIP-parity env.
5. Record exact commit/tree identities, WordPress versions, fixture hashes,
   commands, and outcomes. Static proof must not be summarized as runtime
   proof; local parity must not be summarized as WordPress VIP production
   approval.

## Stop Conditions

- Any write would overwrite or stage the twelve pre-existing Drupal proof
  changes.
- Canonical Contentful nesting requires an architecture choice beyond the
  documented Contentful container relationships.
- Tightening a shared wp-meta validator breaks non-block executor kinds or
  requires relaxing the authenticated artifact boundary.
- A runtime gate needs credentials, production data, or a non-disposable
  environment.
- A security fix changes benign golden output without an explicit fidelity
  decision and regression evidence.

## Draft Acceptance Criteria

- All demonstrated false-green probes fail before their fixes and pass only
  after the intended contract is satisfied.
- Unrelated WordPress planner prose cannot pass the block-planner oracle.
- Malformed names, missing local block assets, and lint-only package scripts
  fail both static block scan paths with named gate IDs.
- The tracked executor fixture is runtime-eligible and passes packet,
  materialization, static certification, isolated build, WPCS, Plugin Check,
  editor insertion/save, selector/text frontend proof, identity binding, and
  cleanup.
- Canonical Contentful list/quote/table AST imports with zero invalid or missing
  blocks; hostile comment sequences preserve exact attribute values without
  freeform residue; a real editor mutation and restoration survive reload.
- No documented hostile Drupal element, attribute, or unsafe anchor survives
  any supported conversion branch, and each removal is reported exactly once.
- Drupal semantic oracle mutations fail, an unchanged second run performs zero
  body writes, a changed body performs one write, and write failure fails the
  run.
- Editor/frontend evidence is current, tied to exact inputs, and clearly
  separated from static and host-unit evidence.
- All unrelated user changes remain unmodified and unstaged.

## Critic Handoff

The cold review must challenge scope, whether the proposed oracles can still
false-green, security reachability/severity, source fidelity, runtime cost,
dirty-tree safety, and whether any claim should be narrowed instead of adding
code. General WordPress, security, QA, and performance perspectives are
required before implementation.

## Cold Critique Of Draft V1

Three independent reviews returned `REVISE`; none reported a Critical finding.
The plan's central distinction survived review, but the first draft was not an
executable control document. The accepted findings were:

1. Three Git roots need three serial packets, independent checkpoints, review
   gates, and rollback boundaries.
2. `wp-meta-skills` distribution includes skill mirrors, Claude/Codex agent
   launchers, `skills.sh.json`, and `MANIFEST.sha256`; changing only two skill
   trees would break the publication contract.
3. Runtime assertions cannot be attached to a generic fixture. The fixture,
   rubric, materializable packet, block identity, selector, and visible text
   must describe one exact artifact.
4. Planner checks must be section-local and conditional; keyword presence is
   not a block plan. Both static scan paths should consume one strict metadata
   validator, and a `build` script must be an admitted WordPress build command,
   not arbitrary shell text.
5. The migration planner owns source-to-block transformation. Existing
   migration implementations remain repository-owned; the plugin executor does
   not regenerate them.
6. Contentful needs a pre-write canonical-AST validator. Production block
   serialization must call WordPress core; a test-only helper may be parity
   checked but cannot become a runtime fallback.
7. Registry membership and migration-contract allowlisting are different
   checks. Unsupported nodes must be accounted for rather than flattened into
   “missing blocks.”
8. Drupal's source policy must cover `DOMComment` block-delimiter injection,
   forbidden elements, attributes, every URI sink, style, SVG/MathML, and form
   controls before block serialization. Security severity depends on actual
   stored/public reachability, not converter output alone.
9. Mutation tests must kill the intended gate while unrelated gates stay green.
10. Editor proof needs a real dirty transition, successful persistence,
    reload, restoration, and final database hash—not a no-op save.
11. Drupal idempotence needs unit call counts plus live content, timestamp,
    revision, hook, and cache-invalidation evidence.
12. Ignored output does not isolate sibling app-code, databases, themes,
    containers, or networks. Heavy gates need disposable runtime identities,
    hard timeouts, cost records, and cleanup receipts.

## Revised Execution Contract — V2

Status: candidate approved plan for short cold re-review. Execution is serial by
repository. A packet may advance only after its focused RED/GREEN tests, full
host gates, and required critic verdict pass. Heavy runtimes run once per frozen
tree and are rerun only if a later edit touches that runtime surface.

### Phase 0 — Trust, Identity, And Runtime Ownership

The source-data trust path is:

`less-trusted CMS author/export → privileged migration operator → stored WordPress content → editor/public render`.

Converter-policy bypasses are Major content-integrity defects. They become
stored-XSS findings only if hostile source data survives WordPress filtering and
executes on the public surface. Admin-equivalent behavior is reported
separately.

Freeze these identities before editing or installing dependencies:

| Packet | Base and runtime floor | Admitted existing state |
|---|---|---|
| WPMS | `bbafaf62b4742fc02445ab88924b2d91ed77bfdd`; Python 3.13; PHP 8.5; current isolated profile pins WordPress 7.0.1 | clean source tree; new branch `codex/gutenberg-contracts-2026-07-16` |
| CFWP | `cb17fbc403c48872b67a111886aff3ae8b78c9fa`; WordPress >=6.5; PHP >=8.2 | clean `main`; `composer.lock` SHA-256 `75ec7b9f...08aa02`; `package-lock.json` SHA-256 `39ad5e2a...920808` |
| D2WP | `eee0539`; runtime proof is WordPress 7.0 local VIP parity; Composer requires PHP >=8.2 | twelve dirty proof files; porcelain digest `edc1422f...3247`; binary-diff digest `2bbe33b9...f182` |

The existing `wp-dest-lab` is not disposable: it has untracked plugins,
packages, sync tooling, themes, and tools. No revised gate may point at it. D2WP
runtime work must use a new admitted app-code copy and unique VIP dev-env slug,
or remain explicitly blocked. The orchestrator must accept and record the slug,
base URL, and `D2WP_DEST`; destructive sync/staging requires a run-owned marker
and exact managed-path preimage. Contentful runtime proof must use a newly
created disposable wp-env instance and destroy it after evidence is copied.

Every runtime packet records branch/HEAD, porcelain status and hashes, fixture
hash, runtime identity, database/site identity, active theme, site URL, start and
end times, timeout, exit status, cleanup time, remaining containers/networks,
and a post-run state comparison. No credentials are retained.

### Packet 1 — wp-meta-skills Tool Contract

Base: `bbafaf62b4742fc02445ab88924b2d91ed77bfdd`.

Owned surfaces:

- block and migration skill mirrors under `.agents/skills` and
  `.claude/skills`;
- matching `.claude/agents` and `.codex/agents` launchers;
- block/migration eval fixtures, metadata, rubrics, examples, and suite docs;
- shared block metadata/output-contract validators and focused tests;
- current runtime documentation, `skills.sh.json` validation, and regenerated
  `MANIFEST.sha256`.

Implementation sequence:

1. Add RED tests proving the unrelated-API planner false green, malformed block
   names, wrong metadata types, missing local `file:` edges, registered-handle
   versus file-array handling, and lint/test/`echo build` script false greens.
   Each mutant invokes the focused checker below identity binding and must fail
   the named target check while unrelated checks remain green.
2. Add one shared strict metadata validator consumed by
   `artifact_snapshot_scan.py` and `validate_wordpress_artifact.py`. Enforce
   WordPress namespace/name grammar; required-string and object types; bounded
   `apiVersion`; local `file:` containment/existence; handles versus local
   files; and either concrete `register_block_type()` evidence or an approved
   `@wordpress/scripts` build command with the existing lock/profile controls.
3. Add section-local block-plan checks:
   - `Block Scope`: static, dynamic, hybrid, variation, pattern, transform, or
     Interactivity classification;
   - `Metadata And Attribute Plan`: explicit attributes/sources/defaults and
     saved-markup contract, or an explicit no-attributes decision;
   - `Render And Interaction Plan`: `save()` versus
     `render.php`/`render_callback` and failure behavior;
   - `Compatibility And Migration Plan`: deprecated/migrate/transforms or
     evidence that no saved contract changes;
   - `Test Strategy`: distinct editor and frontend oracles.
4. Freeze the executor fixture to the exact Acme runtime-card specification
   already represented by the materializable packet. Update its rubric and add
   exact `runtime_assertions` for `acme/runtime-card`,
   `.wp-block-acme-runtime-card`, and `Runtime block smoke`.
5. Define the routing contract mechanically:
   - block planner/executor owns repository-defined custom-block metadata,
     rendering, assets, and saved-content compatibility;
   - migration planner owns source mapping, serialization, unsupported-content
     accounting, idempotence/rollback, semantic oracles, editor proof, and
     frontend proof;
   - migration code remains repo-owned. Add a migration-planner fixture,
     rubric, and domain check for that handoff.
6. Replace current-facing runtime commands with the exact direct-artifact
   digest/evidence/assertion/full-profile/strict-profile command. Label external
   Interactivity/deprecation results historical-only.
7. Regenerate every publication mirror and manifest, then run distribution,
   frontmatter, install, exact-API, strict suite, packet, materializer, static,
   focused pytest, full non-Docker, and the frozen isolated block runtime once.

Checkpoint: a scoped WPMS commit plus general WordPress and QA acceptance. Add
security review only if REST, AJAX, upload, private-preview, or executable
runtime boundaries change beyond the existing authenticated artifact path.

### Packet 2 — Contentful Migration Gutenberg Contract

Base: `cb17fbc403c48872b67a111886aff3ae8b78c9fa` on a new scoped branch. Dependency
installation must leave both lockfile hashes unchanged.

Owned surfaces: Rich Text validation/rendering, Gutenberg inspection,
Contentful fixtures/tests, focused wp-env scripts, and directly affected
README/checklist/mapping claims.

Implementation sequence:

1. Add `RichTextAstValidator` and invoke it for every mapped locale/Rich Text
   field before model options, run records, media, users, posts, or meta are
   written. Enforce one document root, top-level allowlist, canonical container
   relationships, typed text/marks/targets, table hierarchy, void-node rules,
   and a bounded depth/node count. Invalid input fails with an exact source path
   and produces zero WordPress mutations.
2. Replace the golden Rich Text shapes with canonical list-item, quote, table
   cell/header, and nested-list structures. Add RED tests before changing the
   renderer. Make rendering container-aware and account explicitly for every
   unsupported node; do not emit nested top-level block delimiters inside table
   cell HTML.
3. In production, serialize the custom dynamic block only with
   `get_comment_delimited_block_content()`/`serialize_block_attributes()`.
   There is no production fallback. An injected test serializer may exist only
   in tests and must differentially match live core for `-->`, `<!--`, `<`,
   `>`, `&`, quotes, backslashes, Unicode, and multiline values.
4. Extract a testable Gutenberg inspector and keep independent fields for block
   API availability, parse/serialize equality, non-whitespace freeform residue,
   registry membership after `init`, migration-contract allowlisting,
   placeholder leakage, and checked-post count. Registered-but-disallowed and
   zero checked posts fail. Editor validity remains a separate oracle.
5. Create a disposable clone post from the imported fixture. The browser gate
   identifies a deterministic paragraph, proves initial clean state, inserts a
   unique marker, proves dirty state, saves successfully, reloads and observes
   the marker, restores exact original content, saves/reloads, and matches the
   baseline database content hash. The clone is deleted in always-run cleanup;
   import idempotence evidence is never mutated.
6. Add a WordPress runtime serialization smoke that parses exactly one intended
   custom block, recovers exact hostile-corpus values, and finds no freeform
   residue. Record current core/plugin versions and fixture hashes.
7. Run focused/full PHPUnit and lint, then once on the frozen tree run disposable
   wp-env product/editor/frontend, smoke, classic, unresolved-reference, and
   cleanup gates under a whole-run deadline. Reconcile docs only from those
   results.

Checkpoint: a scoped CFWP commit plus general WordPress and security acceptance.

### Packet 3 — Drupal-To-WordPress Gutenberg Contract

Base: `eee0539` on a new branch carrying, but never staging, the admitted proof
diff. Owned paths exclude `proof/**` and the existing `wp-dest-lab` entirely.

The V1 source policy is explicit:

- admit only `h1`–`h6`, `p`, `ul`, `ol`, `li`, `blockquote`, `pre`,
  `table`, `thead`, `tbody`, `tfoot`, `tr`, `th`, `td`, `div`, `figure`,
  `figcaption`, `hr`, `a`, `span`, `strong`, `b`, `em`, `i`, `u`, `s`,
  `code`, `br`, `img`, and `drupal-media` source elements;
- admit attributes per element rather than globally: `a[href,title]`,
  `img[src,alt,width,height]`, `ol[start,reversed,type]`,
  `th[colspan,rowspan,scope]`, `td[colspan,rowspan]`, and
  `drupal-media[data-entity-type,data-entity-uuid,data-align,data-caption]`;
  every other attribute is removed and recorded once;
- remove all source `DOMComment` nodes, including Gutenberg delimiters, with one
  loss row per comment;
- remove `script`, `iframe`, `object`, `embed`, `style`, `meta`, `link`,
  `base`, `template`, SVG, MathML, and form controls with their contents and
  one row per removed source node;
- unwrap every other unlisted standard or custom element after recursively
  applying the same policy to its children, discard its attributes, and record
  the wrapper loss once; arbitrary fallback HTML is not preserved in V1;
- remove all `on*` and `style` attributes for V1;
- allow URI-bearing attributes only for `http`, `https`, `mailto`, `tel`,
  relative paths, and fragments; reject `javascript`, `data`, `vbscript`, and
  protocol-relative/unknown schemes;
- apply the source-policy pass once to the whole DOM, then rewrite anchors and
  dispatch sanitized children to block serializers;
- do not apply a blind KSES pass over completed Gutenberg comments. A separate
  live reachability gate records any WordPress filtering between generated,
  stored, rendered, and browser states.

Implementation sequence:

1. Add corpus RED tests for every policy item across paragraph, heading, list,
   unwrapped unknown wrappers, top-level anchor, comment-delimiter, and mixed
   benign/hostile shapes. Include `meta[http-equiv=refresh]`, external `link`,
   `base`, `template`, a custom element, and an unlisted attribute. Assert exact
   one-per-source-node/attribute drop identity and preserved admitted benign
   text.
2. Implement the one-pass source policy and anchor order, then rerun the corpus
   and existing benign golden serialization tests.
3. Make Pass B fail closed and byte-idempotent. Unit gates require zero update
   calls for unchanged bytes, exactly one call with `$wp_error=true` for changed
   bytes, and failed/resumable runs for `WP_Error` and zero returns.
4. Enforce one separate semantic gate ID for every existing oracle property:
   text, href, attachment file, alt, caption, list count, visible unsafe-link
   text, and absent executable href. Each single-fact stored-content mutant must
   kill only its target gate, restore the original, and return the full suite to
   green. Alias-link expansion follows these P0/P1 closures.
5. Decide and document Drupal editor scope as editability proof. Use a disposable
   cloned post and the same dirty/save-success/persist/restore/final-DB-hash
   protocol as Contentful; record revision delta and recursive block validity.
6. Add live Pass-B instrumentation immediately around unchanged run two:
   content SHA-256, modified timestamps, revision count, run/checkpoint state,
   and a run-owned MU-plugin counting `post_updated`, `save_post_standard`, and
   `clean_post_cache` for the target. Unchanged means zero target events;
   changed body means one importer write and no unrelated-post activity. Local
   timing bounds regression only; it is not a production-performance claim.
7. Add a disposable-runtime contract: configurable unique slug/base URL/dest,
   run-owned marker and managed-path preimage, real terminate-then-kill wall
   timeout, unique `var/gutenberg-hardening/<run-id>` evidence, and always-run
   cleanup receipts. Create a fresh app-code/runtime; never sync to the existing
   dirty sibling.
8. Run focused PHPUnit, full PHPUnit/smoke/PHPStan, bounded converter timing, and
   once on the frozen tree the isolated product/editor/frontend/vertical stack.
   Record raw generated bytes, stored `post_content`, `the_content()` output,
   public DOM behavior, importing capability context, and cleanup. Calibrate
   severity from this evidence.

Checkpoint: a scoped D2WP commit that excludes all admitted proof diffs, plus
general WordPress, security, QA, and performance acceptance.

### Executable Acceptance Matrix

Every implemented row must record repository, layer, exact command, fixture
digest, expected gate ID, single-fact mutant, evidence path, hard timeout,
cleanup oracle, and negative space.

| ID | Repository/layer | Target gate and required outcome |
|---|---|---|
| WPMS-PLAN-01 | WPMS/static | unrelated-API block plan fails section-local domain contract |
| WPMS-META-01 | WPMS/static | bad name, type, local edge, and fake build each fail its exact metadata gate |
| WPMS-RUN-01 | WPMS/runtime | frozen runtime-card passes bound isolated build/editor/frontend/full profile and cleanup |
| CFWP-AST-01 | CFWP/unit | each malformed canonical relationship fails pre-write with exact AST path and zero mutations |
| CFWP-SER-01 | CFWP/WP runtime | hostile corpus produces one intended custom block, exact attributes, no freeform residue |
| CFWP-EDIT-01 | CFWP/editor+DB | clone dirty/save/reload/restore succeeds and final DB hash equals baseline |
| CFWP-VERIFY-01 | CFWP/WP runtime | freeform, unregistered, registered-disallowed, zero-post cases fail distinct IDs |
| D2WP-POLICY-01 | D2WP/unit | every enumerated hostile node/attribute/URI/comment is removed once; benign content remains |
| D2WP-SEM-01 | D2WP/WP unit+runtime | every oracle property has an independently killed semantic gate |
| D2WP-WRITE-01 | D2WP/unit+WP runtime | unchanged run has zero writes/events/state drift; changed body has one owned write |
| D2WP-EDIT-01 | D2WP/editor+DB | clone dirty/save/reload/restore succeeds and final DB hash equals baseline |
| D2WP-REACH-01 | D2WP/frontend | generated/stored/rendered/DOM evidence calibrates content-integrity versus XSS reachability |
| ALL-CLEAN-01 | all/operations | source and admitted runtime state match post-run allowlist; no undeclared residual resources |

### Deferred Work

- arbitrary custom HTML, inline CSS preservation, SVG/MathML, iframe/form, and
  broad embedded-media fidelity;
- cross-browser and real WordPress VIP production approval;
- adoption/replacement of the full `contentful/rich-text` architecture;
- external generated-block Interactivity/deprecation adapters;
- Drupal alias expansion until policy, comments, writes, and semantic gates are
  green;
- production performance claims from local timing.

### V2 Critic Handoff

Re-review only plan-blocking questions: packet isolation, complete distribution
surfaces, exact fixture identity, no production serializer fallback, pre-write
AST validation, explicit DOM policy, target-gate mutation proof, live write and
editor instrumentation, runtime ownership, timeouts, and cleanup. `ACCEPT` may
include non-blocking implementation details; any unresolved Critical/Major
finding returns the plan to revision.

## V2 Review Result

`ACCEPT` — general WordPress/tooling, WordPress security/source-integrity, and
QA/performance/operations reviewers reported no unresolved Critical or Major
plan blocker after the exact Drupal allowlist amendment. Implementation must
still pass repository-local post-change criticism; plan acceptance is not code
acceptance.
