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
    "@wordpress/scripts": "^30.0.0"
  }
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
This packet targets block API version 3 and WordPress 6.5 or newer. The generated tree is not a standalone plugin; runtime activation requires a host that calls `register_block_type()` with the block directory. The deterministic wp-env proof may synthesize that host as a disposable wrapper, but that wrapper is not part of the generated block artifact.

## Security Performance And Accessibility Notes
The block has no user-supplied attributes, SQL, REST, AJAX, uploads, remote HTTP calls, or persistent options. Frontend output is dynamic and escaped with `esc_html__()` while wrapper attributes are constrained through `wp_kses_data( get_block_wrapper_attributes() )`. The visible text is plain text so the frontend smoke can assert both the `wp-block-acme-runtime-card` wrapper class and the rendered copy. The package uses `@wordpress/scripts` for the standard WordPress build path.

## Deviation Log
No deviations from the smoke spec. The packet intentionally omits a permanent plugin wrapper so block executor outputs remain block-only.

## Verification Notes
- Run `python3 evals/harness/validate_wordpress_executor_packet.py --executor block --packet <candidate-output.md>` for the deterministic packet contract.
- Run `python3 evals/harness/materialize_wordpress_executor_packet.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --overwrite` to materialize the block files.
- Run `python3 evals/harness/certify_wordpress_executor_artifact.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --result-dir <result-dir> --overwrite` for the saved-packet artifact gate.
- Run `npm run build` before claiming compiled asset readiness. This smoke artifact ships an `index.asset.php` file so the runtime oracle can run without a build step.
- Run block validation, editor smoke, and frontend smoke. The live wp-env proof is `python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path <generated-block-dir> --artifact-kind block --editor-insert-render-smoke --write --run-id <run-id>`.
- Use Playwright-backed editor smoke before claiming the block can be inserted and rendered from the editor.

## Critic Handoff
Send the materialized files, certification output, and runtime smoke output to `wordpress-critic` for block architecture and release calibration, then to `wordpress-performance-critic` for build, editor, and frontend performance review.
