## Spec Conformance
Implements the approved Acme Runtime Card dynamic block spec without adding REST routes, AJAX endpoints, admin-post handlers, SQL, uploads, remote HTTP calls, production write commands, or a permanent plugin wrapper. Generated paths: `package.json`, `blocks/runtime-card/block.json`, `blocks/runtime-card/index.asset.php`, `blocks/runtime-card/index.js`, and `blocks/runtime-card/render.php`.

The generated artifact is a pure block file tree. A host plugin, theme, or disposable runtime harness must call `register_block_type()` on `blocks/runtime-card` before runtime claims are made.

## Generated Block Files
### package.json
```json
{
  "scripts": {
    "build": "wp-scripts build blocks/runtime-card/index.js --output-path=blocks/runtime-card/build",
    "start": "wp-scripts start"
  },
  "devDependencies": {
    "@wordpress/scripts": "32.4.1"
  }
}
```

### package-lock.json
```json
{
  "kind": "approved-lock-profile",
  "version": 1,
  "approved_lock_profile": "block-scripts-32.4.1-smoke",
  "sha256": "990d9a67783977a5a4c54035666ebc48f7aaac8cdf69f2313caf2a17b317fa33",
  "manifest_sha256": "e2259282345ac90cb5645507efd0daba536b2742be3eab676db10fd7fc1fb4f6"
}
```

### blocks/runtime-card/block.json
```json
{
  "apiVersion": 3,
  "name": "acme/runtime-card",
  "title": "Runtime Card",
  "category": "widgets",
  "description": "A disposable dynamic block used by the WordPress executor runtime oracle.",
  "textdomain": "acme-runtime-card",
  "editorScript": "file:./index.js",
  "render": "file:./render.php"
}
```

### blocks/runtime-card/index.asset.php
```php
<?php
/**
 * Editor script asset metadata for the runtime card block.
 *
 * @package AcmeRuntimeCard
 */

return array(
	'dependencies' => array( 'wp-blocks', 'wp-element', 'wp-i18n' ),
	'version'      => '0.1.0',
);
```

### blocks/runtime-card/index.js
```js
( function ( blocks, element, i18n ) {
	const el = element.createElement;
	const __ = i18n.__;

	blocks.registerBlockType( 'acme/runtime-card', {
		edit: function () {
			return el( 'p', {}, __( 'Runtime block smoke', 'acme-runtime-card' ) );
		},
		save: function () {
			return null;
		},
	} );
} )( window.wp.blocks, window.wp.element, window.wp.i18n );
```

### blocks/runtime-card/render.php
```php
<?php
/**
 * Render template for the runtime card block.
 *
 * @package AcmeRuntimeCard
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

?>
<div <?php echo wp_kses_data( get_block_wrapper_attributes() ); ?>>
	<?php echo esc_html__( 'Runtime block smoke', 'acme-runtime-card' ); ?>
</div>
```

## Compatibility Notes
This packet is designed for block API version 3 and WordPress 6.5 or newer; the static artifact oracle does not prove that compatibility floor, and a current-runtime pass does not substitute for a 6.5 matrix run. The generated tree is not a standalone plugin; runtime activation requires a host that calls `register_block_type()` with the block directory. The deterministic wp-env proof may synthesize that host as a disposable wrapper, but that wrapper is not part of the generated block artifact.

## Security Performance And Accessibility Notes
The block has no user-supplied attributes, SQL, REST, AJAX, uploads, remote HTTP calls, or persistent options. Frontend output is dynamic and escaped with `esc_html__()` while wrapper attributes are constrained through `wp_kses_data( get_block_wrapper_attributes() )`. The visible text is plain text so the frontend smoke can assert both the `wp-block-acme-runtime-card` wrapper class and the rendered copy. The package uses `@wordpress/scripts` for the standard WordPress build path.

## Deviation Log
No deviations from the smoke spec. The packet intentionally omits a permanent plugin wrapper so block executor outputs remain block-only.

## Verification Notes
- Run `python3 evals/harness/validate_wordpress_executor_packet.py --executor block --packet <candidate-output.md>` for the deterministic packet contract.
- Run `python3 evals/harness/materialize_wordpress_executor_packet.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --overwrite` to materialize the block files.
- Run `python3 evals/harness/certify_wordpress_executor_artifact.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --result-dir <result-dir> --overwrite` for the saved-packet artifact gate.
- Use the current direct-artifact runtime command below. It binds the exact pre-stage digest and evidence ID, requires the build plus provisioned strict full profile, and supplies the reviewed block name, selector, and visible text instead of inferring them from the artifact or packet prose.

```bash
artifact="<generated-block-dir>"
digest="$(PYTHONPATH=evals/harness python3 - "$artifact" <<'PY'
import sys
from pathlib import Path
from artifact_staging import digest_regular_tree
print(digest_regular_tree(Path(sys.argv[1])))
PY
)"
python3 evals/harness/run_wordpress_runtime_smoke.py \
  --artifact-path "$artifact" \
  --artifact-kind block \
  --expected-artifact-digest "$digest" \
  --evidence-id generated-runtime-card-full-profile-YYYYMMDD \
  --block-build-smoke \
  --block-name acme/runtime-card \
  --editor-insert-render-smoke \
  --expected-frontend-selector .wp-block-acme-runtime-card \
  --expected-frontend-text "Runtime block smoke" \
  --provision-full-profile \
  --strict-full-profile \
  --write \
  --run-id generated-runtime-card-full-profile-YYYYMMDD \
  --timeout-sec 300
```

- A green packet, materializer, or static artifact result is not runtime proof. Current runtime claims require the command above and its matching evidence record.
- Inside the isolated command, `--block-build-smoke` runs the approved `npm run build`; the execution artifact then undergoes block validation against `block.json`, editor smoke that inserts/edits the block in wp-admin, and frontend smoke that renders the selector-scoped block on a page.
- External generated-block Interactivity and deprecation modes are unsupported by the current isolated artifact path; historical built-in fixture results do not prove this packet.

## Critic Handoff
Send the materialized files, certification output, and runtime smoke output to `wordpress-critic` for block architecture and release calibration, then to `wordpress-performance-critic` for build, editor, and frontend performance review.
