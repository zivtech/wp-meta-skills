# Deep Dive: WooCommerce Transition Gates - 2026-07-02

Target 4 from `docs/wordpress-assist-research-plan-2026-07-02.md`. Status:
research brief, not an approved spec. Legend: [fetched] = read from
github.com/woocommerce/woocommerce trunk (or named repo) this session;
[snippet-only] = search snippet; [known, unverified] = established behavior
not re-confirmed against source this session.

Three gates in one critic: HPOS compatibility, checkout-blocks hook gaps,
and template drift. The combined three-gate CI scanner appears genuinely
unowned — Woo core only tracks *self-declared* compatibility (it scans
nothing), and the one existing HPOS scanner is an admin-UI plugin with no CI
mode, no checkout coverage, and no template coverage.

## 1. HPOS compatibility, precisely

Legacy patterns that break, per the HPOS recipe book [fetched:
`docs/features/high-performance-order-storage/recipe-book.md`]:

| Legacy pattern | Why it breaks | Replacement |
|---|---|---|
| `get/update/add/delete_post_meta( $order_id, ... )` | Order meta lives in `wc_orders_meta`; writes land on the `shop_order_placehold` placeholder row and are **silently invisible** to Woo reads | `wc_get_order( $id )` + `get_meta()`/`update_meta_data()`/`save()` |
| `WP_Query`/`get_posts()` with `post_type => shop_order` | Orders are not posts | `wc_get_orders()` / `WC_Order_Query` |
| Direct SQL on `wp_posts`/`wp_postmeta` | Tables not authoritative | `OrderUtil::get_table_for_orders()`/`get_table_for_order_meta()`, or CRUD |
| `get_post()`/`get_post_status()`/`get_post_type()` on order IDs | Placeholder/nothing | `wc_get_order()`, `$order->get_status()`, `OrderUtil::get_order_type()`, `OrderUtil::is_order()` |
| Order-ID-is-post-ID assumptions (`save_post_shop_order`, `before_delete_post`, `transition_post_status`, `add_meta_box(..., 'shop_order')`, hand-built edit links) | Custom admin list table; post lifecycle hooks never fire | `OrderUtil::get_order_admin_edit_url()`, `is_order_edit_screen()`; Woo order hooks (`woocommerce_new_order`, `woocommerce_update_order`, `woocommerce_order_status_changed`... [known, unverified as exact list]) |

`OrderUtil` public surface [fetched: `src/Utilities/OrderUtil.php`]:
`custom_orders_table_usage_is_enabled()`, `custom_orders_table_data_sync_is_enabled()`,
`is_custom_order_tables_in_sync()`, `get_post_or_object_meta()`,
`get_post_or_order_id()`, `is_order()`, `get_order_type()`,
`get_order_admin_edit_url()`, `is_order_edit_screen()`,
`is_order_list_table_screen()`, `get_table_for_orders()`,
`get_table_for_order_meta()`, `get_count_for_type()`.
**Exact-API contract note: `OrderUtil::get_post_or_order_object()` is NOT in
trunk — a commonly hallucinated API. Use `wc_get_order()`.**

Detection surfaces Woo provides:
- `FeaturesUtil::declare_compatibility( $feature_id, $plugin_file, $positive = true )`
  on `before_woocommerce_init` [fetched: `src/Utilities/FeaturesUtil.php`].
  Feature IDs: `custom_order_tables` (HPOS), `cart_checkout_blocks`
  [fetched: `src/Internal/Features/FeaturesController.php`]. The
  incompatible-plugins screen is **self-declaration tracking, not scanning**;
  undeclared plugins are "uncertain".
- `wp wc hpos` CLI [fetched: `docs/.../cli-tools.md`]: `status`,
  `enable [--with-sync]`, `disable`, `count_unmigrated`, `sync`,
  **`verify_data [--re-migrate]`** (not the older `verify_cot_data`),
  `diff <order_id> --format=json`, `backfill <order_id> --from=... --to=...`,
  `cleanup`. There is **no `compatibility-info` subcommand** — do not put it
  in the skill.

## 2. Checkout-blocks compatibility, precisely

Extension surface (all [fetched] from Woo docs tree):
- **Store API**: `POST /wc/store/v1/checkout` (auth via `Nonce:` header or
  Cart Token; response has `order_id`, `payment_result.payment_status`).
- **Additional Checkout Fields API**:
  `woocommerce_register_additional_checkout_field()` after
  `woocommerce_init`; locations `contact|address|order`; read-back via
  `CheckoutFields` service or meta prefixes `_wc_billing/`, `_wc_other/`;
  validation hooks `woocommerce_sanitize_additional_field`,
  `woocommerce_validate_additional_field`.
- **Slot/Fill**: exactly four documented slots — `ExperimentalOrderMeta`,
  `ExperimentalOrderShippingPackages`, `ExperimentalOrderLocalPickupPackages`,
  `ExperimentalDiscountsMeta` — via `@woocommerce/blocks-checkout`,
  `registerPlugin` scope `woocommerce-checkout`. All `Experimental`-prefixed
  and documented as subject to change (churn risk for remediation text).
- **IntegrationInterface** registered on
  `woocommerce_blocks_checkout_block_registration`; client reads
  `getSetting('{name}_data')`.
- **ExtendSchema** via `StoreApi::container()` after
  `woocommerce_blocks_loaded`; helpers
  `woocommerce_store_api_register_endpoint_data()`,
  `woocommerce_store_api_register_update_callback()`.
- **Payment methods**: JS `registerPaymentMethod` from
  `@woocommerce/blocks-registry`; PHP `AbstractPaymentMethodType` on
  `woocommerce_blocks_payment_method_type_registration`; server processing
  via `woocommerce_rest_checkout_process_payment_with_context`.

**The gate's grep list** — `hook-alternatives.md` [fetched] marks ~75 hooks
"Not supported" in block checkout, including: all checkout render actions
(`woocommerce_before_checkout_form`, `woocommerce_checkout_billing`,
`woocommerce_before/after_checkout_billing_form`,
`woocommerce_review_order_before_submit` and the whole
`woocommerce_review_order_*` family, `woocommerce_checkout_terms_and_conditions`,
`woocommerce_checkout_update_order_review`) and key filters
(`woocommerce_checkout_fields` — "editing core fields not supported; adding
is via Additional Checkout Fields API", `woocommerce_order_button_text/html`,
`woocommerce_checkout_create_order`, `woocommerce_gateway_title`). Still
fire: lifecycle hooks and the Store API equivalents
(`woocommerce_store_api_checkout_order_processed`,
`woocommerce_store_api_checkout_update_order_meta`,
`woocommerce_store_api_validate_cart_item`).

Deterministic detection = three greps: (1) unsupported-hook usage;
(2) `declare_compatibility('cart_checkout_blocks'` presence/boolean;
(3) any block-surface usage (fields API, block registration hooks,
`IntegrationInterface`, `AbstractPaymentMethodType`, `registerPaymentMethod`,
slot/fill imports, ExtendSchema helpers). Classic hooks + zero block surface
+ no declaration = "silently absent on block checkout".

## 3. Template drift gate

Mechanism confirmed in `WC_Admin_Status` and the System Status REST
controller [both fetched]: core templates carry `@version`;
`scan_template_files()` enumerates; `get_file_version()` regex-extracts from
the first 8KB; override located via `wc_locate_template()`; staleness =
`version_compare(override, core, '<')`. REST: `GET /wc/v3/system_status` →
`theme.overrides[{file, version, core_version}]` + `has_outdated_templates`.
No dedicated WP-CLI command verified — use `wp eval` calling
`WC_Admin_Status` internals, or authenticated REST.

Two tiers: **static** (no WordPress: diff `theme/woocommerce/**` `@version`
headers against a pinned Woo release zip; missing `@version` header is
itself a finding) and **runtime** (`wp eval` in wp-env — also catches
overrides injected via `woocommerce_locate_template` filters).

## 4. Runtime verification (wp-env smoke)

The existing harness's MCP-adapter smoke (installs an extra plugin zip, runs
`wp` commands, `blocked` semantics) is the direct precedent. Additions:

- **Provisioning `--woocommerce-smoke`**: add the Woo zip (pinned version for
  CI) to `.wp-env.json` plugins; disable coming-soon; enable COD
  (`wp wc payment_gateway update cod --enabled=true --user=admin`); create a
  product (`wp wc product create` [fetched: using-wc-cli.md]; `--user`
  semantics [known, unverified] — verify at build; `wp eval` +
  `wc_create_order()` is the deterministic fallback).
- **HPOS order-path smoke `--hpos-smoke enabled|legacy|both`**:
  `wp wc hpos enable` **without sync** (sync masks breakage) → create order →
  exercise plugin order path → assert: no fatals; order in
  `wc_get_orders()`; `wc_get_order($id)->get_meta($key)` returns the
  expected value; **divergence detector**: `get_post_meta()` vs
  `$order->get_meta()` disagreement = data written to the wrong store; with
  sync, `wp wc hpos diff <id> --format=json` empty + `verify_data` clean.
- **Checkout smoke `--checkout-smoke shortcode|blocks|both`**: two checkout
  pages (`[woocommerce_checkout]` shortcode vs `wp:woocommerce/checkout`
  block); Store API E2E with COD (`GET /wc/store/v1/cart` → capture nonce →
  `add-item` → `POST checkout` → assert `order_id`). Hook-gap assertion:
  plugin sentinel present in shortcode-page HTML (curl — server-rendered),
  absent in block-checkout DOM (Playwright — client-rendered React); that
  plus no declaration = FAIL with Slot/Fill or fields-API remediation.

## 5. Repo fit

`docs/wordpress/coverage-matrix.md` already names the gap ("No dedicated
WooCommerce critic yet"). **Recommendation: new critic skill
`woocommerce-transition-critic`** (critic-shaped: verdict over an existing
codebase), following `wordpress-security-critic/SKILL.md` structure, with
Phase 0 scope classification (plugin vs site vs theme), a reachability gate
(a `get_post_meta` hit matters only if the variable is plausibly an order
ID), an Exact API contract populated from §1-3, and a verdict packet:
`READY | AT-RISK | BLOCKED` + three finding groups (HPOS / checkout-blocks /
template-drift), each finding naming the exact replacement API, plus a
verification-oracle handoff naming the exact harness command. The critic
*consumes* the deterministic scanner output rather than re-deriving it.
Scanner lives at `evals/harness/scan_woocommerce_transition.py` + pytest.

## 6. Static gate design

Tier: Python regex + line-context heuristics (matches the repo's
Python-only tooling; the hard problem — is `$id` an order ID? — is data-flow
that AST answers only heuristically too; encode confidence explicitly).

| rule_id | pattern sketch | confidence |
|---|---|---|
| `hpos.postmeta_on_order` | `(get\|update\|add\|delete)_post_meta(\s*\$\w*order` | definite-break when arg matches `order`; needs-review otherwise in files referencing `wc_get_order\|shop_order\|WC_Order` |
| `hpos.order_post_query` | `post_type => 'shop_order(_refund)?'` in `get_posts`/`WP_Query` context | definite-break |
| `hpos.direct_sql` | `$wpdb->` + `posts\|postmeta` + order token in statement | definite-break; without order token, needs-review |
| `hpos.get_post_on_order` | `get_post(_status\|_type)?(\s*\$\w*order` | definite-break |
| `hpos.post_lifecycle_hooks` | `add_action('save_post_shop_order\|before_delete_post\|transition_post_status'...` | needs-review (fires only in legacy/sync mode) |
| `hpos.no_declaration` | no `declare_compatibility('custom_order_tables'` in an order-touching plugin | needs-review (policy) |
| `checkout.unsupported_hook` | `add_action\|add_filter` on any of the ~75 names from hook-alternatives.md | definite-gap |
| `checkout.fields_filter` | `add_filter('woocommerce_checkout_fields'` | definite-gap; remediation = fields API |
| `checkout.no_block_surface` | unsupported hooks > 0 AND zero block-surface matches AND no declaration | definite-gap (composite) |
| `template.stale_override` | `@version` compare per §3 | definite (version math) |

Finding JSON (`"schema": "woocommerce-transition-scan/v1"`): per-finding
`rule`, `gate`, `severity: definite-break|definite-gap|needs-review`,
`file`/`line`/`evidence`, `why`, `remediation_api[]`,
`declared_compatibility{}`, `runtime_oracle` (exact harness command);
summary with per-gate status the harness consumes.

Existing art: [robertdevore/hpos-compatibility-scanner](https://github.com/robertdevore/hpos-compatibility-scanner)
(GPL-2.0-or-later, admin-UI plugin, CSV export; no CI mode, no
checkout/template coverage) — record as reference-only in
`reuse-ledger.md`. Woo core scans nothing. No checkout-hook-gap or
template-drift CI tool found.

## 7. Fixture plan (all clean-room GPL-compatible; Woo core is GPLv3 on wp.org)

- **(a) `acme-legacy-order-meta`** (definite HPOS break): writes
  `update_post_meta( $order_id, '_acme_ref', ... )` on
  `woocommerce_checkout_order_processed`. Static: definite-break. Runtime:
  under HPOS-no-sync, `wc_get_order($id)->get_meta('_acme_ref')` empty while
  `get_post_meta()` non-empty → divergence check fails exactly as designed.
- **(b) `acme-checkout-notice`** (silent block-checkout gap): only hooks
  `woocommerce_review_order_before_submit` echoing a sentinel. Static:
  unsupported hook + no block surface. Runtime: sentinel in shortcode HTML
  (curl), absent from block-checkout DOM (Playwright).
- **(c) `acme-crud-order-notes`** (must pass): `wc_get_order()`/CRUD +
  `save()`, declares both `custom_order_tables` and `cart_checkout_blocks`
  compatibility, optionally registers an additional checkout field. Zero
  findings; order meta visible under HPOS; Store API checkout completes.

## 8. Effort, risks, maintainer questions

**Phases:** P1 static scanner + fixtures + pytest (pure Python, no network).
P2 `--woocommerce-smoke` provisioning + HPOS order-path smoke. P3 checkout
smoke — Store API E2E first (curl-tier), block-checkout DOM assertion last
(highest flake risk; informational-then-strict, mirroring
`--strict-full-profile`). P4 `woocommerce-transition-critic` SKILL + eval
suite + coverage-matrix/AGENTS.md updates.

**Risks:** Woo monthly churn (pin reference Woo version per scanner release;
derive the hook list from `hook-alternatives.md` at build time with a
freshness-check script recording the doc commit hash); block-checkout E2E
flakiness (Store API E2E is the required gate; DOM sentinel informational
first); blind spots (Subscriptions/premium extensions can't be fixtures —
the subscriptions-invisible failure class is representable only
synthetically; regex misses dynamic hooks/wrapper functions/query builders —
`needs-review` severity + critic judgment is the containment, stated in
negative space); `wp wc shop_order create`/`--user` semantics unverified —
`wp eval` + `wc_create_order()` fallback.

**Maintainer questions:**
1. Pin Woo version in CI smoke (reproducible, goes stale) vs `latest-stable`
   (realistic, nondeterministic)? Suggest pinned + optional `--live` mode.
2. V1 scope: plugin readiness only, or site-level audit (theme overrides +
   all active plugins)? Changes inputs, runtime cost, packet shape.
3. Run the sync/compat-mode matrix (`enable --with-sync` + `hpos diff`) in
   V1, or is no-sync HPOS-only the fail-fast default? (No-sync is strictest
   and cheapest; the matrix triples runtime.)
