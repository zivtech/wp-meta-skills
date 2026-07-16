## Spec Conformance
Implements the approved Acme Deprecated Card static block spec without adding REST routes, AJAX endpoints, admin-post handlers, SQL, uploads, remote HTTP calls, production write commands, or a permanent plugin wrapper. Generated paths: `package.json`, `deprecation-smoke.json`, `fixtures/deprecated-v1.html`, `blocks/deprecated-card/block.json`, `blocks/deprecated-card/index.asset.php`, and `blocks/deprecated-card/index.js`.

The generated artifact is a pure block file tree. A host plugin, theme, or disposable runtime harness must call `register_block_type()` on `blocks/deprecated-card` before runtime claims are made. The legacy fixture proves a deprecated static block version, not a dynamic render callback.

## Generated Block Files
### package.json
```json
{
  "scripts": {
    "build": "wp-scripts build --source-path=blocks/deprecated-card --output-path=blocks/deprecated-card/build",
    "start": "wp-scripts start --source-path=blocks/deprecated-card --output-path=blocks/deprecated-card/build"
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
  "approved_lock_profile": "block-scripts-32.4.1-deprecation",
  "sha256": "66a25aaf8dd6545320c35fb2efa525a473e5bf7fde8a1f496feb726de93d3812",
  "manifest_sha256": "157195077dc1169f556b3f193fa597e5d4f1c0fa33c5d41e37a389136ba973a3"
}
```

### deprecation-smoke.json
```json
{
  "oldContentFile": "fixtures/deprecated-v1.html",
  "expectedMigratedText": "Runtime block smoke: Legacy runtime smoke",
  "expectedMigratedAttributeName": "content",
  "expectedMigratedAttribute": "Legacy runtime smoke",
  "expectedSerializedMarker": "<strong>Runtime block smoke:</strong>"
}
```

### fixtures/deprecated-v1.html
```html
<!-- wp:acme/deprecated-card {"text":"Legacy runtime smoke"} -->
<p class="wp-block-acme-deprecated-card">Legacy runtime smoke</p>
<!-- /wp:acme/deprecated-card -->
```

### blocks/deprecated-card/block.json
```json
{
  "apiVersion": 3,
  "name": "acme/deprecated-card",
  "title": "Deprecated Card",
  "category": "widgets",
  "description": "A disposable static block used by the WordPress block deprecation runtime oracle.",
  "textdomain": "acme-deprecated-card",
  "editorScript": "file:./index.js",
  "attributes": {
    "content": {
      "type": "string",
      "source": "html",
      "selector": "span"
    }
  }
}
```

### blocks/deprecated-card/index.asset.php
```php
<?php
/**
 * Editor script asset metadata for the deprecated card block.
 *
 * @package AcmeDeprecatedCard
 */

return array(
	'dependencies' => array( 'wp-blocks', 'wp-block-editor', 'wp-element', 'wp-i18n' ),
	'version'      => '0.1.0',
);
```

### blocks/deprecated-card/index.js
```js
import { registerBlockType } from '@wordpress/blocks';
import { useBlockProps } from '@wordpress/block-editor';
import { createElement } from '@wordpress/element';
import { __ } from '@wordpress/i18n';

const CURRENT_LABEL = __( 'Runtime block smoke:', 'acme-deprecated-card' );

registerBlockType( 'acme/deprecated-card', {
	attributes: {
		content: {
			type: 'string',
			source: 'html',
			selector: 'span',
		},
	},

	edit( { attributes } ) {
		const blockProps = useBlockProps();
		return createElement(
			'p',
			blockProps,
			`${ CURRENT_LABEL } ${ attributes.content || __( 'Legacy runtime smoke', 'acme-deprecated-card' ) }`
		);
	},

	save( { attributes } ) {
		const blockProps = useBlockProps.save();
		return createElement(
			'div',
			blockProps,
			createElement( 'strong', {}, CURRENT_LABEL ),
			' ',
			createElement( 'span', {}, attributes.content || '' )
		);
	},

	deprecated: [
		{
			attributes: {
				text: {
					type: 'string',
					source: 'html',
					selector: 'p',
				},
			},

			migrate( { text } ) {
				return {
					content: text || '',
				};
			},

			save( { attributes } ) {
				return createElement( 'p', useBlockProps.save(), attributes.text || '' );
			},
		},
	],
} );
```

## Compatibility Notes
This packet is designed for block API version 3 and WordPress 6.5 or newer; the static artifact oracle does not prove that compatibility floor, and a current-runtime pass does not substitute for a 6.5 matrix run. It follows the WordPress Deprecation API shape: the current `save()` emits the current markup, the deprecated version defines its own `attributes` and `save()`, and `migrate()` renames the old `text` attribute to the current `content` attribute. The generated tree is not a standalone plugin; runtime activation requires a host that calls `register_block_type()` with the block directory. The deterministic `wp-env` proof may synthesize that host as a disposable wrapper, but that wrapper is not part of the generated block artifact.

## Security Performance And Accessibility Notes
The block has no user-supplied SQL, REST, AJAX, uploads, remote HTTP calls, persistent options, or server-side rendering. The legacy fixture is static serialized block content used only by the runtime oracle. The current saved output keeps the default `wp-block-acme-deprecated-card` wrapper class and plain text content so the editor migration and frontend assertions can inspect the exact migrated result.

## Deviation Log
No deviations from the deprecation smoke spec. The packet intentionally omits a permanent plugin wrapper so block executor outputs remain block-only.

## Verification Notes
- Run `python3 evals/harness/validate_wordpress_executor_packet.py --executor block --packet <candidate-output.md>` for the deterministic packet contract.
- Run `python3 evals/harness/materialize_wordpress_executor_packet.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --overwrite` to materialize the block files.
- Run `python3 evals/harness/certify_wordpress_executor_artifact.py --executor block --packet <candidate-output.md> --out-dir <generated-block-dir> --result-dir <result-dir> --overwrite` for the saved-packet artifact gate.
- Use the current direct-artifact command below for the supported standard build, registration, editor insertion, and current-markup frontend render profile. It does not exercise the legacy fixture or `migrate()` path.

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
  --evidence-id generated-deprecated-card-standard-full-profile-YYYYMMDD \
  --block-build-smoke \
  --block-name acme/deprecated-card \
  --editor-insert-render-smoke \
  --expected-frontend-selector .wp-block-acme-deprecated-card \
  --expected-frontend-text "Runtime block smoke:" \
  --provision-full-profile \
  --strict-full-profile \
  --write \
  --run-id generated-deprecated-card-standard-full-profile-YYYYMMDD \
  --timeout-sec 300
```

- External generated-block deprecation runtime mode is unsupported by the current isolated artifact path. The 2026-06-21 built-in fixture result is historical diagnostic evidence only and cannot establish current support for this packet.
- Inside the supported isolated command, `--block-build-smoke` runs the approved `npm run build`; the execution artifact then undergoes block validation against `block.json`, editor smoke that inserts/edits the current block in wp-admin, and frontend smoke that renders the selector-scoped current block on a page.
- Do not claim legacy markup migration, attribute migration, or post-save current serialization until a fixture-owned external-artifact deprecation adapter is implemented and re-proved.

## Critic Handoff
Send the materialized files, certification output, and runtime smoke output to `wordpress-critic` for block deprecation architecture and release calibration, then to `wordpress-performance-critic` for build, editor, and migration-path performance review.
