# WordPress Skills Reuse Ledger

No copied upstream passages are included in the initial V1 skill prompts.

The initial prompts are original Zivtech protocols informed by the candidate survey. Skill files include compatible reference notes naming upstream sources that should be used as evaluation comparators or future attribution anchors.

Active policy: direct copied or closely adapted third-party prompt text remains blocked inside `zivtech-meta-skills` until root license handling is standardized. See `license-reuse-policy.md`.

## Reference-Only Entries

| Local Area | Source | Commit | License | Reuse Class | Rationale |
|---|---|---:|---|---|---|
| WordPress planners/executors/critics | WordPress/agent-skills | `aa735ea7111c7924ee988306bcef70439e17dec9` | GPL-2.0-or-later | Reference only | Official coverage map and comparator |
| Performance critic | elvismdev/claude-wordpress-skills | `0ac0bbd5fd7c2a91f45af8ec3f5282537e52b075` | MIT | Reference only | Focused performance-review comparator |
| Migration/page-builder coverage | respira-press/agent-skills-wordpress | `e39a5c788e5a39d05157f804c8fd0c5a4f5e07a2` | MIT | Reference only | Broad site migration and page-builder skill inventory |
| Broad community comparison | jorgerosal/wordpress-skills | `8c964424d05ba34b3ea5641f7181d4c13829e06f` | MIT | Reference only | Broad WordPress skill inventory across ACF, security, CI/CD, REST, and WooCommerce |

## Tooling Dependencies (fetched at install time, never vendored)

The API-existence lint (`evals/harness/wp_api_lint.py`) shells out to a
Composer-installed toolchain pinned by `evals/harness/php-tools/composer.lock`.
Only `composer.json` and `composer.lock` are committed; the `vendor/` tree is
gitignored and fetched by each environment (2026-07-02).

| Package | Version | License | Handling |
|---|---:|---|---|
| phpstan/phpstan | 2.2.3 | MIT | Fetched dependency; invoked as a subprocess |
| php-stubs/wordpress-stubs | 7.0.0 | MIT | Fetched dependency; loaded by PHPStan as scan files |
| johnbillion/wp-compat | 1.5.0 | MIT | Fetched dependency; PHPStan rule set plus `symbols.json` used for did-you-mean suggestions |
| wp-hooks/wordpress-core | 1.12.0 | GPL-3.0 | Transitive dependency of wp-compat, consumed inside the fetched `vendor/` tree at analysis time — by wp-compat's PHPStan rules and (since the 2026-07-02 phase-2 merge) by the lint's hooks engine, which reads `vendor/wp-hooks/wordpress-core/hooks/*.json` directly at run time. Update 2026-07-03: the repository relicensed to GPL-3.0, so committing a hooks snapshot is now license-compatible if ever wanted (with a ledger entry); the vendor-side consumption remains the current implementation. |
| playwright | 1.58.0 | Apache-2.0 | Locked by `runtime-images/browser/package-lock.json`; installed while the trusted browser image is built and executed only in the final mount-free browser service |

## Committed Data Extraction Entries

`evals/harness/data/wp-symbols.json` (built by `scripts/build-wp-symbol-db.py`)
is a committed, MIT-sources-only snapshot for the lint's native engine. It
contains symbol names, deprecation versions, successor API names, and
introduced-in versions — no prose, descriptions, or code are copied.

| Data | Source | Ref | License | Extracted facts |
|---|---|---|---|---|
| Function/class existence, `@deprecated` versions and replacements | php-stubs/wordpress-stubs | `v7.0.0` | MIT | Symbol names, deprecation version, successor API name (via PHP reflection over the stubs) |
| Per-function `since` versions | johnbillion/wp-compat `symbols.json` | `trunk` (WP 7.0 data) | MIT | Function name → introduced-in version |
# Plan 009 sandbox feasibility inventory (verified 2026-07-14)

Step 0 records the official Node, Composer, Python, Playwright, WordPress,
WP-CLI, and MariaDB images in `evals/harness/container-images.json`. Each entry
contains its reviewed tag (provenance only), OCI index digest, linux/amd64 and
linux/arm64 child digests, purpose, and upstream license. Execution must select
the platform child digest and must not resolve the tag. The WordPress 7.0.1
source archive URL and SHA-256 are recorded in the same inventory.

The npm runner locks use registry packages under their package-published
licenses. Fixture Composer acquisition is HTTPS ZIP dist-only; inert `source`
metadata in Composer's generated lock is not an allowed fallback.
The no-secrets Linux job installs Pytest 8.4.2 from PyPI without a credentialed
cache; Pytest is MIT-licensed. The boundary job uses no actions or helper
images: it fetches the exact public `$GITHUB_SHA` over HTTPS without credentials
and uses the GitHub-hosted runner's Python and Docker installations.

On 2026-07-14 the mutable provenance tags for Node, Python, and WordPress moved.
Their official OCI indexes and linux/amd64 and linux/arm64 child manifests were
re-reviewed together; the inventory and Node acquisition profiles now record
those replacements. Composer, Playwright, WP-CLI, and MariaDB still resolved to
their previously reviewed identities. Execution remains child-digest-only; the
tags are checked solely as a fail-closed signal that a new provenance review is
required.

The final generated-code runtime additionally derives three local images from
the immutable WordPress 7.0.1, MariaDB 11.8.5, and Playwright 1.58.0 platform
digests. Its WordPress build consumes the separately hashed WordPress core,
WP-CLI 2.12.0, and Plugin Check 2.0.0 inputs. The committed browser runner uses
the npm lock above; generated package dependencies are never copied into that
runner. Derived image tags are run-scoped handles, not provenance, and are
deleted after evidence collection. No upstream source or prompt prose is
vendored by these build inputs beyond the recorded archives and fetched locked
dependencies under their stated licenses.
