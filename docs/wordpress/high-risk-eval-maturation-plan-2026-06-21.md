# WordPress High-Risk Eval Maturation Plan - 2026-06-21

## Purpose

This plan defines what it would take to upgrade the remaining high-risk
WordPress eval suites beyond smoke scaffolds.

The current monorepo recovery PR does not claim this work is complete. PR #11
claims mature WordPress skill protocols, deterministic contract/oracle gates,
standalone package validation, and executor/runtime proof for the plugin and
block paths named in the handoff. It does not claim focused benchmark maturity
for every high-risk critic or planner surface.

## Current Observed State

At the start of this plan, the following suites were still one-fixture smoke
scaffolds:

- `evals/suites/wordpress-security-critic`
- `evals/suites/wordpress-performance-critic`
- `evals/suites/wordpress-planner.migration`
- `evals/suites/wordpress-blueprint-executor`

`evals/suites/wordpress-security-critic` has been expanded beyond one fixture:
it now has the original smoke fixture plus focused REST/AJAX authorization,
input/SQL/output handling, upload/filesystem-boundary, and post-P2
security-gate-consumption fixtures. It is still not mature benchmark evidence
because independent QA/test-critic or semantic review is still missing. A
saved-output contract run now exists at
`evals/results/wordpress-security-critic-saved-outputs-20260621/`: generation
passed for 12/12 skill and baseline outputs, deterministic output-contract
results exist for every saved output, and the three focused skill outputs
passed the output contract 3/3. Baseline outputs did not pass the strict
skill-output contract, and the legacy broad smoke skill output failed the
strict output contract, so this remains contract evidence rather than benchmark
evidence. Deterministic lexical answer-key coverage now exists at
`evals/results/wordpress-high-risk-answer-key-20260621/`; the focused skill
lane scored composite 0.936 across the three non-smoke fixtures. Main-agent QA
review of the answer-key interpretation now exists at
`evals/results/wordpress-high-risk-answer-key-20260621/qa-review.md` and
accepts the run with reservations for internal diagnostic use.
The `security-gate-consumption-v1` fixture, sidecar, and rubric were added on
2026-07-06 after that saved-output run; fresh saved outputs are required before
including it in score claims.

`evals/suites/wordpress-performance-critic` has also been expanded beyond one
fixture: it now has the original smoke fixture plus focused query/cache,
autoload/transient/invalidation, and frontend-assets/render-path fixtures. It
is still not mature benchmark evidence because independent QA/test-critic or
semantic review is still missing.
A saved-output contract run now exists at
`evals/results/wordpress-performance-critic-saved-outputs-20260621/`:
generation passed for 12/12 skill and baseline outputs, deterministic
output-contract results exist for every saved output, the three focused skill
outputs passed the output contract 3/3, and the legacy smoke skill output also
passed. Baseline outputs did not pass the strict skill-output contract, so this
remains contract evidence rather than benchmark evidence. Deterministic lexical
answer-key coverage now exists in
`evals/results/wordpress-high-risk-answer-key-20260621/`; the focused skill
lane tied `baseline-zero-shot` on composite at 0.844, with higher API coverage
but lower recall. Main-agent QA review now exists and rejects any performance
superiority claim from this run. Follow-up inspection of
`query-cache-pressure-v1` found one semantic scorer miss around measurement
language and one real archived-output gap around the custom-table scale
evidence boundary; the performance critic prompt now makes both boundaries
explicit for future generations without changing the archived scores. Scoped
main-agent semantic annotation now exists at
`evals/results/wordpress-high-risk-answer-key-20260621/performance-query-cache-semantic-annotation.md`;
it records the archived `query-cache-pressure-v1` skill output as semantically
`3/4` on must-detect items, with the custom-table scale-evidence boundary still
missing. Regenerated post-repair evidence now exists at
`evals/results/wordpress-performance-critic-query-cache-regenerated-20260621/`
for the single `query-cache-pressure-v1` skill output; it passed the output
contract `1/1`. Deterministic answer-key coverage for that regenerated output
exists at
`evals/results/wordpress-performance-critic-query-cache-regenerated-answer-key-20260621/`
and scored recall `1.000`, API coverage `0.700`, specificity `1.000`, and
composite `0.900` for this one fixture. This proves the amended prompt can
produce the repaired boundary language on the focused fixture; it is not
full-suite regeneration, baseline regeneration, variance evidence, independent
review, or a benchmark-superiority result. Full focused post-repair
regeneration now exists at
`evals/results/wordpress-performance-critic-regenerated-focused-20260621/`:
generation passed `9/9` across `skill`, `baseline-zero-shot`, and
`baseline-few-shot`; focused skill outputs passed the output contract `3/3`;
baseline lanes remained `0/6` on the strict skill-output contract.
Deterministic answer-key coverage for that regenerated focused run exists at
`evals/results/wordpress-performance-critic-regenerated-focused-answer-key-20260621/`.
Condition composites were `skill` `0.915`, `baseline-zero-shot` `0.845`, and
`baseline-few-shot` `0.862`. This is directional lexical/contract evidence,
not independent review, variance evidence, or accepted benchmark evidence.

`evals/suites/wordpress-planner.migration` has also been expanded beyond one
fixture: it now has the original smoke fixture plus focused legacy-CMS content
mapping, URL/redirect/permalink preservation, and cutover/rollback/
reconciliation fixtures. It is still not mature benchmark evidence because
answer-key interpretation still needs independent QA/test-critic or semantic
review. A saved-output contract run
now exists at
`evals/results/wordpress-planner-migration-saved-outputs-20260621/`:
generation passed for 12/12 skill and baseline outputs, deterministic
output-contract results exist for every saved output, the three focused skill
outputs passed the output contract 3/3, and the legacy smoke skill output also
passed. Baseline outputs did not pass the strict skill-output contract, so this
remains contract evidence rather than benchmark evidence. Deterministic lexical
answer-key coverage now exists in
`evals/results/wordpress-high-risk-answer-key-20260621/`; the focused skill
lane scored composite 0.954. Main-agent QA review now exists and accepts this
as internal diagnostic evidence with reservations.

`evals/suites/wordpress-blueprint-executor` has also been expanded beyond one
fixture: it now has the original smoke fixture plus focused minimal-plugin
environment, block/theme reproduction, unsupported-feature boundary, and
self-contained plugin launch fixtures. It exposes packet, materializer,
certifier, launch-readiness, and Playground smoke oracles, with each evidence
boundary recorded separately. A static certification run exists at
`evals/results/wordpress-blueprint-executor-static-cert-20260621/`: the three
VFS-backed focused saved packets passed packet contract, materialization, and
static `blueprint.json` artifact certification 3/3. Their launch-readiness
preflight at
`evals/results/wordpress-blueprint-executor-launch-preflight-20260621/` remains
blocked because those Blueprints reference VFS plugin/theme ZIP payloads that
are not bundled in committed evidence. A separate self-contained packet passed
static certification at
`evals/results/wordpress-blueprint-executor-self-contained-static-cert-20260621/`,
passed launch-readiness preflight at
`evals/results/wordpress-blueprint-executor-self-contained-launch-preflight-20260621/`,
and passed one browser-observed Playground smoke at
`evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/`.
Main-agent QA review now exists at
`evals/results/wordpress-blueprint-executor-self-contained-playground-smoke-20260621/qa-review.md`
and accepts the smoke as narrow internal runtime evidence with reservations.
This proves one self-contained artifact can launch and render its expected admin
page; it is not benchmark evidence, independent QA/test-critic review, or proof
for the VFS-backed packets.

## What This Is Not

This plan is not a benchmark result.

It is not evidence of variance reduction, reviewer superiority, production
readiness, public release readiness, or credentialed third-party provider
behavior. It is also not a reason to reopen the old frontier-model
review-quality comparison target; that path already produced a directional null
and should stay closed unless the measurement target changes.

## Minimum Acceptance Gates

Do not mark the high-risk eval evidence item complete until each matured suite
meets these gates:

- at least three focused fixtures per suite, or an explicit narrower-scope
  reason approved in the suite README;
- fixture metadata that names risk class, expected WordPress APIs, expected
  verification surfaces, and negative-space boundaries;
- rubrics that score the exact risk under test instead of generic helpfulness;
- saved candidate outputs for at least skill and baseline lanes;
- deterministic output-contract oracle run on saved outputs;
- deterministic answer-key coverage or an explicit rationale for why a fixture
  requires non-lexical review only;
- strict suite validation passing for the matured suite;
- independent QA/test-critic review or semantic annotation before any public
  benchmark claim;
- no external-provider secrets, tokens, or credentials in fixtures, outputs, or
  result archives.

For executor suites, also require packet and artifact gates where applicable.
For Blueprint runtime claims, require a recorded WordPress Playground launch
smoke before claiming runtime behavior.

## Security Critic Lane

Target suite: `evals/suites/wordpress-security-critic`.

Minimum fixtures:

- REST/AJAX authorization failure:
  - Risk: endpoint or action accepts privileged mutation with weak or missing
    capability checks.
  - Expected APIs/surfaces: `register_rest_route()`, `permission_callback`,
    `current_user_can()`, `wp_ajax_*`, `wp_ajax_nopriv_*`,
    `check_ajax_referer()`, `wp_verify_nonce()`.
  - Must catch: authentication without authorization, nonce-as-capability
    confusion, public `nopriv` mutation, and absent test path.

- Input, SQL, and output handling:
  - Risk: unsafe request handling reaches query or rendered output.
  - Expected APIs/surfaces: `$wpdb->prepare()`, `sanitize_text_field()`,
    `sanitize_key()`, `absint()`, `wp_unslash()`, `esc_html()`, `esc_attr()`,
    `esc_url()`, `wp_kses_post()`.
  - Must catch: interpolated SQL, unslashed superglobals, late escaping gaps,
    and false confidence from sanitization alone.

- Upload and filesystem boundary:
  - Risk: plugin accepts upload/path input that can become arbitrary file write,
    MIME bypass, or unsafe local include.
  - Expected APIs/surfaces: `wp_handle_upload()`, `wp_check_filetype_and_ext()`,
    `wp_mkdir_p()`, `wp_normalize_path()`, `realpath()`, `plugin_dir_path()`.
  - Must catch: trusting file extension, missing capability/nonce pairing, path
    traversal, and unsupported claims about malware scanning.

Required evidence:

- saved outputs that use the critic verdict scale correctly;
- output-contract oracle pass for each saved output;
- answer-key or fixture oracle that checks the expected finding classes;
- README update documenting what the suite does not cover, including full
  supply-chain review and CVE monitoring.

Current progress: fixture, metadata, and rubric scaffolding now cover all three
minimum fixture classes above plus the post-P2 gate-consumption class. Saved skill and baseline outputs plus
deterministic output-contract oracle archives exist in
`evals/results/wordpress-security-critic-saved-outputs-20260621/`; the three
focused skill outputs passed the output contract 3/3. Deterministic answer-key
coverage exists in `evals/results/wordpress-high-risk-answer-key-20260621/`.
Main-agent QA review exists at
`evals/results/wordpress-high-risk-answer-key-20260621/qa-review.md` and
accepts this lane as internal diagnostic evidence with reservations. The lane
remains incomplete for benchmark claims until independent/semantic review
exists, and the `security-gate-consumption-v1` fixture still needs a fresh
saved-output pass before it is included in scores.

## Performance Critic Lane

Target suite: `evals/suites/wordpress-performance-critic`.

Minimum fixtures:

- Query and cache pressure:
  - Risk: slow `WP_Query` shape, avoidable count queries, expensive meta query,
    or missing cache strategy.
  - Expected APIs/surfaces: `WP_Query`, `no_found_rows`, `fields => 'ids'`,
    `update_post_meta_cache`, `update_post_term_cache`, `pre_get_posts`,
    `wp_cache_get()`, `wp_cache_set()`.
  - Must catch: query-shape risk and require measurement before claiming a fix.

- Autoloaded options, transients, and invalidation:
  - Risk: large autoloaded options, unbounded transients, stale cache, or
    invalidation that hides data changes.
  - Expected APIs/surfaces: `get_option()`, `update_option()`,
    `set_transient()`, `get_transient()`, `delete_transient()`,
    `wp option list --autoload=on`, object-cache metrics.
  - Must catch: cache-as-fix handwaving and missing invalidation trigger.

- Frontend assets and render path:
  - Risk: unnecessary blocking assets, editor-only assets on frontend, missing
    dependencies, or expensive render callbacks.
  - Expected APIs/surfaces: `wp_enqueue_script()`, `wp_enqueue_style()`,
    `wp_register_script()`, `wp_register_style()`, `render_callback`,
    `block.json`, Core Web Vitals, Query Monitor.
  - Must catch: no measurement plan, no before/after boundary, and fixes that
    only move work between requests.

Required evidence:

- saved outputs with exact bottleneck expectations;
- output-contract oracle pass for each saved output;
- rubric checks for named tools such as Query Monitor, `wp profile`, browser
  performance traces, or database/query logs where appropriate;
- README update documenting that the suite does not prove production latency or
  capacity without real traffic and environment data.

Current progress: fixture, metadata, and rubric scaffolding now cover all three
minimum fixture classes above. Saved skill and baseline outputs plus
deterministic output-contract oracle archives exist in
`evals/results/wordpress-performance-critic-saved-outputs-20260621/`; the
three focused skill outputs passed the output contract 3/3. Deterministic
answer-key coverage exists in
`evals/results/wordpress-high-risk-answer-key-20260621/`; it did not show a
clean lexical skill edge over `baseline-zero-shot`. Follow-up inspection exists
at
`evals/results/wordpress-high-risk-answer-key-20260621/performance-query-cache-recall-review.md`.
Scoped semantic annotation also exists at
`evals/results/wordpress-high-risk-answer-key-20260621/performance-query-cache-semantic-annotation.md`.
Regenerated post-repair evidence for the single `query-cache-pressure-v1` skill
output exists at
`evals/results/wordpress-performance-critic-query-cache-regenerated-20260621/`,
with deterministic answer-key coverage at
`evals/results/wordpress-performance-critic-query-cache-regenerated-answer-key-20260621/`.
Full focused post-repair regeneration now exists at
`evals/results/wordpress-performance-critic-regenerated-focused-20260621/`,
with deterministic answer-key coverage at
`evals/results/wordpress-performance-critic-regenerated-focused-answer-key-20260621/`.
The lane remains incomplete for benchmark claims until independent review
exists, with long-run variance measurement added if public comparison claims
need it.

## Migration Planner Lane

Target suite: `evals/suites/wordpress-planner.migration`.

Minimum fixtures:

- Drupal 7 or legacy CMS to WordPress content mapping:
  - Risk: fields, taxonomies, authors, revisions, and media relationships are
    flattened into a generic import plan.
  - Expected surfaces: source schema inventory, post type and taxonomy mapping,
    media attachment mapping, field-transform table, sample-row validation.
  - Must catch: unsupported certainty when source exports are absent.

- URL, redirect, and permalink preservation:
  - Risk: migration plan loses canonical URLs, search equity, and editorial
    redirects.
  - Expected surfaces: permalink model, redirect map, `wp rewrite flush`,
    `wp search-replace`, crawl comparison, 404 sampling.
  - Must catch: redirect plan without acceptance criteria.

- Cutover, rollback, and reconciliation:
  - Risk: plan has no freeze window, delta migration, rollback point, or data
    reconciliation.
  - Expected surfaces: dry-run import, row counts, checksum/sample validation,
    editorial QA queue, rollback checkpoint, launch runbook.
  - Must catch: single-shot migration optimism and missing ownership.

Required evidence:

- saved outputs with explicit assumption registers and negative-space
  statements;
- output-contract oracle pass for each saved output;
- rubric checks for source-data uncertainty, validation commands, rollback
  boundaries, and editorial workflow;
- README update documenting that the suite does not prove a real migration
  without source extracts and stakeholder acceptance criteria.

Current progress: fixture, metadata, and rubric scaffolding now cover all three
minimum fixture classes above. Saved skill and baseline outputs plus
deterministic output-contract oracle archives exist in
`evals/results/wordpress-planner-migration-saved-outputs-20260621/`; the three
focused skill outputs passed the output contract 3/3. Deterministic answer-key
coverage exists in `evals/results/wordpress-high-risk-answer-key-20260621/`.
Main-agent QA review exists at
`evals/results/wordpress-high-risk-answer-key-20260621/qa-review.md` and
accepts this lane as internal diagnostic evidence with reservations. The lane
remains incomplete for benchmark claims until independent/semantic review
exists.

## Blueprint Executor Lane

Target suite: `evals/suites/wordpress-blueprint-executor`.

Minimum fixtures:

- Minimal reproducible plugin environment:
  - Risk: Blueprint file installs or activates the wrong thing, omits setup
    steps, or hides manual prerequisites.
  - Expected surfaces: `blueprint.json`, `preferredVersions`, `steps`,
    `installPlugin`, `activatePlugin`, login/user setup where needed.

- Block or theme reproduction environment:
  - Risk: generated Blueprint does not preserve the block/theme state needed for
    the reported bug or demonstration.
  - Expected surfaces: uploaded files, theme/plugin activation, sample content,
    site options, permalink state, and clear manual follow-up.

- Failure/unsupported-feature boundary:
  - Risk: Blueprint claims Playground can reproduce behavior that still needs
    external services, credentials, custom containers, or persistent state.
  - Expected surfaces: explicit unsupported sections, manual setup notes, and
    deterministic fallback instructions.

Required evidence:

- saved executor packets beyond the smoke fixture;
- packet-contract oracle pass;
- materializer pass;
- static `blueprint.json` artifact oracle pass;
- certifier pass with result directory;
- at least one recorded Playground launch smoke before claiming runtime
  behavior;
- README update documenting that static Blueprint validity is not the same as
  live Playground reproduction.

Current progress: fixture, metadata, and rubric scaffolding now cover all three
minimum fixture classes above plus a self-contained launch fixture. Focused
VFS-backed saved executor packets plus packet/materializer/static/certifier
result archives exist in
`evals/results/wordpress-blueprint-executor-static-cert-20260621/`; all three
passed static certification. Their launch-readiness preflight remains blocked
on missing VFS payloads. The self-contained packet now has static
certification, launch-readiness preflight, and one recorded Playground launch
smoke plus a main-agent QA review accepting that smoke with reservations. The
lane remains incomplete for benchmark claims until independent review exists and
any VFS-backed runtime claims have supplied payloads and their own launch
evidence.

## Suggested Order

1. Get independent QA/test-critic review or a broader manual semantic annotation
   sample before presenting security, performance, or migration quality as
   benchmarked evidence.
2. Get independent/owner review of the self-contained Blueprint launch smoke,
   and supply the missing VFS payloads only if the VFS-backed packets need
   runtime claims.
3. Run full-suite/baseline regeneration or long-run variance measurement only
   for a changed measurement target, not for frontier-model review-quality
   superiority.

## Done Boundary

The todo item "Upgrade per-skill eval evidence beyond smoke where risk warrants
it" remains open after this plan is added.

It can be closed only when the focused fixtures, rubrics, saved outputs,
contract/oracle runs, strict validation, independent/semantic review gates, and
Blueprint Playground launch evidence where applicable exist and are referenced
from the suite READMEs or pilot-result docs.
