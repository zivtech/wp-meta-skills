## Spec Conformance
Implements the approved Acme Interactive Counter dynamic block spec without adding REST routes, AJAX endpoints, admin-post handlers, SQL, uploads, remote HTTP calls, production write commands, or a permanent plugin wrapper. Generated paths: `package.json`, `blocks/interactive-counter/block.json`, `blocks/interactive-counter/index.asset.php`, `blocks/interactive-counter/index.js`, `blocks/interactive-counter/view.js`, and `blocks/interactive-counter/render.php`.

The generated artifact is a pure block file tree. A host plugin, theme, or disposable runtime harness must call `register_block_type()` on `blocks/interactive-counter` before runtime claims are made.

## Generated Block Files
### package.json
```json
{
  "scripts": {
    "build": "wp-scripts build --source-path=blocks/interactive-counter --output-path=blocks/interactive-counter/build --experimental-modules",
    "start": "wp-scripts start --source-path=blocks/interactive-counter --output-path=blocks/interactive-counter/build --experimental-modules"
  },
  "dependencies": {
    "@wordpress/interactivity": "6.48.1"
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
  "approved_lock_profile": "block-interactivity-6.48.1",
  "sha256": "53f635a658e1e4504ec41a5c405aa3230566ecbd529f1d137b41c13b30ffc4cc",
  "manifest_sha256": "71b29ec85d0ccffab3ef9d10616eb3ab61829546981e24a5ab17a844c8528c97"
}
```

### blocks/interactive-counter/block.json
```json
{
  "apiVersion": 3,
  "name": "acme/interactive-counter",
  "title": "Interactive Counter",
  "category": "widgets",
  "description": "A disposable dynamic block used by the WordPress Interactivity API runtime oracle.",
  "textdomain": "acme-interactive-counter",
  "editorScript": "file:./index.js",
  "viewScriptModule": "file:./view.js",
  "render": "file:./render.php",
  "supports": {
    "interactivity": true
  }
}
```

### blocks/interactive-counter/index.asset.php
```php
<?php
/**
 * Editor script asset metadata for the interactive counter block.
 *
 * @package AcmeInteractiveCounter
 */

return array(
	'dependencies' => array( 'wp-blocks', 'wp-element', 'wp-i18n' ),
	'version'      => '0.1.0',
);
```

### blocks/interactive-counter/index.js
```js
import { registerBlockType } from '@wordpress/blocks';
import { createElement } from '@wordpress/element';
import { __ } from '@wordpress/i18n';

registerBlockType( 'acme/interactive-counter', {
	edit() {
		return createElement( 'p', {}, __( 'Runtime block smoke', 'acme-interactive-counter' ) );
	},
	save() {
		return null;
	},
} );
```

### blocks/interactive-counter/view.js
```js
import { store, getContext } from '@wordpress/interactivity';

store( 'acmeInteractiveCounter', {
	actions: {
		increment() {
			const context = getContext();
			context.count += 1;
		},
	},
} );
```

### blocks/interactive-counter/render.php
```php
<?php
/**
 * Render template for the interactive counter block.
 *
 * @package AcmeInteractiveCounter
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

?>
<div
	<?php
	echo wp_kses_data(
		get_block_wrapper_attributes(
			array(
				'data-wp-interactive' => 'acmeInteractiveCounter',
				'data-wp-context'     => wp_json_encode(
					array(
						'count' => 0,
					)
				),
			)
		)
	);
	?>
>
	<p><?php echo esc_html__( 'Runtime block smoke', 'acme-interactive-counter' ); ?></p>
	<p>
		<?php echo esc_html__( 'Interactive count:', 'acme-interactive-counter' ); ?>
		<span data-wp-text="context.count">0</span>
	</p>
	<button type="button" data-wp-on--click="actions.increment">
		<?php echo esc_html__( 'Increment', 'acme-interactive-counter' ); ?>
	</button>
</div>
```

## Compatibility Notes
This packet is designed for block API version 3 and WordPress 6.5 or newer, where `viewScriptModule` and the `@wordpress/interactivity` Script Module are available; the static artifact oracle does not prove that compatibility floor, and a current-runtime pass does not substitute for a 6.5 matrix run. The `build` and `start` scripts use `--experimental-modules` because WordPress script modules require that `wp-scripts` path. The generated tree is not a standalone plugin; runtime activation requires a host that calls `register_block_type()` with the block directory. The deterministic `wp-env` proof may synthesize that host as a disposable wrapper, but that wrapper is not part of the generated block artifact.

## Security Performance And Accessibility Notes
The block has no user-supplied attributes, SQL, REST, AJAX, uploads, remote HTTP calls, or persistent options. Frontend output is dynamic and escaped with `esc_html__()` for text while wrapper attributes are constrained through `wp_kses_data( get_block_wrapper_attributes() )`. The visible text includes `Runtime block smoke` so the existing frontend smoke can assert server rendering, and the Interactivity API state uses local `data-wp-context` plus a `data-wp-on--click` action that increments `context.count` from `0` to `1`.

## Deviation Log
No deviations from the Interactivity API smoke spec. The packet intentionally omits a permanent plugin wrapper so block executor outputs remain block-only.

## Verification Notes
- Run `python3 evals/harness/validate_wordpress_executor_packet.py --executor block --packet <candidate-output.md>` for the deterministic packet contract.
- Run `python3 evals/harness/materialize_wordpress_executor_packet.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --overwrite` to materialize the block files.
- Run `python3 evals/harness/certify_wordpress_executor_artifact.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --result-dir <result-dir> --overwrite` for the saved-packet artifact gate.
- Use the current direct-artifact command below for the supported standard build, registration, editor insertion, and frontend render profile. It does not prove the Interactivity click/state contract.

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
  --evidence-id generated-interactive-counter-standard-full-profile-YYYYMMDD \
  --block-build-smoke \
  --block-name acme/interactive-counter \
  --editor-insert-render-smoke \
  --expected-frontend-selector .wp-block-acme-interactive-counter \
  --expected-frontend-text "Runtime block smoke" \
  --provision-full-profile \
  --strict-full-profile \
  --write \
  --run-id generated-interactive-counter-standard-full-profile-YYYYMMDD \
  --timeout-sec 300
```

- External generated-block Interactivity runtime mode is unsupported by the current isolated artifact path. The 2026-06-21 built-in fixture result is historical diagnostic evidence only and cannot establish current support for this packet.
- Inside the supported isolated command, `--block-build-smoke` runs the approved `npm run build`; the execution artifact then undergoes block validation against `block.json`, editor smoke that inserts/edits the block in wp-admin, and frontend smoke that renders the selector-scoped block on a page.
- Do not claim `viewScriptModule` directive execution or click/state behavior until a fixture-owned external-artifact Interactivity adapter is implemented and re-proved.

## Critic Handoff
Send the materialized files, certification output, and runtime smoke output to `wordpress-critic` for block architecture and release calibration, then to `wordpress-performance-critic` for build, editor, frontend, and Interactivity API performance review.
