# Focused Fixture: Autoloaded Options, Transients, And Invalidation

Review the following WordPress implementation excerpt with
`wordpress-performance-critic`. The review target is option/autoload pressure,
transient shape, and invalidation correctness.

## Artifact Under Review

```php
<?php
/**
 * Plugin Name: Acme Directory Cache
 */

function acme_directory_get_cards() {
	$cards = get_transient( 'acme_directory_cards' );
	if ( false !== $cards ) {
		return $cards;
	}

	$settings = get_option( 'acme_directory_settings', array() );
	$response = wp_remote_get( $settings['api_url'] . '/cards' );
	$cards    = json_decode( wp_remote_retrieve_body( $response ), true );

	set_transient( 'acme_directory_cards', $cards );
	update_option( 'acme_directory_last_payload', $cards );

	return $cards;
}
```

## Expected Review Focus

- Detect growth risk from `update_option()` storing a potentially large payload
  without explicitly deciding autoload behavior.
- Detect unbounded transient lifetime and missing invalidation on card updates,
  settings changes, imports, or remote API freshness boundaries.
- Require measurement and inspection commands such as
  `wp option list --autoload=on`, object-cache metrics, or database option-size
  queries before claiming site-wide impact.
- Detect render-time remote call risk and require HTTP timeout/error handling,
  stale-cache behavior, and retry/circuit-breaker boundaries.
- Avoid treating a transient as a complete fix when invalidation and fallback
  behavior are undefined.

## Required Boundaries

Do not claim the option is autoloaded without checking the actual WordPress
version and `update_option()` behavior. Do not claim production capacity impact
without real traffic, object-cache, and database data.
