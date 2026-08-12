# Review target: Acme Reveal Panel

Review this WordPress block's registration and front-end script with
`wordpress-critic`. Report any issues you find, with a file and line/field
reference and a concrete fix for each. If the registration is sound, say so
explicitly and note what you checked.

**block.json**

```json
{
	"$schema": "https://schemas.wp.org/trunk/block.json",
	"apiVersion": 3,
	"name": "acme/reveal-panel",
	"title": "Reveal Panel",
	"category": "widgets",
	"icon": "editor-expand",
	"description": "A panel that expands and collapses on click.",
	"textdomain": "acme",
	"editorScript": "file:./index.js",
	"editorStyle": "file:./index.css",
	"style": "file:./style-index.css",
	"viewScriptModule": "file:./view.js",
	"render": "file:./render.php",
	"supports": {
		"interactivity": true
	},
	"attributes": {
		"label": {
			"type": "string",
			"default": "Show details"
		}
	}
}
```

**view.js** (the built front-end script referenced above)

```js
import { store, getContext } from '@wordpress/interactivity';

store( 'acme/reveal-panel', {
	actions: {
		toggle() {
			const context = getContext();
			context.isOpen = ! context.isOpen;
		},
	},
} );
```

**render.php**

```php
<?php
/**
 * @var array<string, mixed> $attributes Block attributes, provided by WordPress.
 * @var string               $content    Inner block content, provided by WordPress.
 */

$unique_id = wp_unique_id( 'acme-reveal-panel-' );
?>
<div
	<?php echo get_block_wrapper_attributes(); // phpcs:ignore -- Core helper returns pre-escaped attribute markup. ?>
	data-wp-interactive="acme/reveal-panel"
	<?php echo wp_interactivity_data_wp_context( array( 'isOpen' => false ) ); // phpcs:ignore -- Core helper JSON-encodes and escapes the context attribute. ?>
>
	<button
		data-wp-on--click="actions.toggle"
		data-wp-bind--aria-expanded="context.isOpen"
	>
		<?php echo esc_html( $attributes['label'] ); ?>
	</button>
	<div
		data-wp-bind--hidden="!context.isOpen"
		id="<?php echo esc_attr( $unique_id ); ?>"
	>
		<?php echo wp_kses_post( $content ); ?>
	</div>
</div>
```

## Scope

Static review of the files shown. Name any browser or build-tool check that
would still be needed to confirm an assessment either way. Do not claim
editor-side behavior differs from the front end without evidence, and do not
claim wp-scripts build-configuration issues without seeing the build config.
