# Focused Fixture: Frontend Assets And Render Path

Review the following WordPress block/plugin excerpt with
`wordpress-performance-critic`. The review target is frontend asset loading,
editor/frontend parity, and dynamic render-path work.

## Artifact Under Review

```php
<?php
/**
 * Plugin Name: Acme Events Block
 */

add_action( 'init', 'acme_events_register_block' );
function acme_events_register_block() {
	wp_register_script(
		'acme-events-editor',
		plugins_url( 'build/editor.js', __FILE__ ),
		array( 'wp-blocks', 'wp-element' ),
		'1.0.0',
		false
	);

	wp_enqueue_script(
		'acme-events-front',
		plugins_url( 'build/front.js', __FILE__ ),
		array( 'jquery' ),
		'1.0.0',
		false
	);

	register_block_type(
		__DIR__ . '/build',
		array(
			'editor_script'   => 'acme-events-editor',
			'render_callback' => 'acme_events_render_block',
		)
	);
}

function acme_events_render_block( $attributes ) {
	$response = wp_remote_get( 'https://example.invalid/events' );
	$events   = json_decode( wp_remote_retrieve_body( $response ), true );
	return '<div class="acme-events">' . esc_html( count( $events ) ) . ' events</div>';
}
```

## Expected Review Focus

- Detect unconditional frontend enqueue on `init`, blocking footer choice, and
  unnecessary `jquery` dependency if the script is not needed on every page.
- Detect possible editor-only/frontend confusion: `editor_script` belongs to
  editor loading; frontend assets should be declared through `block.json`,
  `viewScript`, `viewScriptModule`, or conditional enqueue where appropriate.
- Detect render-time remote HTTP calls in `render_callback` and require timeout,
  cache, stale fallback, and measurement boundaries.
- Require concrete measurement: browser performance trace, Core Web Vitals where
  available, Query Monitor/APM for render timing, or synthetic before/after page
  tests.
- Avoid fixes that only move work between requests without reducing total cost
  or clarifying freshness requirements.

## Required Boundaries

Do not claim Core Web Vitals failure without field or lab data. Do not require
removing dynamic rendering if freshness requirements justify it and a measured
cache/fallback plan exists.
