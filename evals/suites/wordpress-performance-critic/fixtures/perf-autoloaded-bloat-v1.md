# Review target: Acme Catalog Sync

Review this WordPress plugin file with `wordpress-performance-critic`. Report
the performance risks you find. For each, give a `file:line` reference,
explain how it is reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Catalog Sync
 * Description: Mirror the upstream product catalog (typically several thousand SKUs) into a local option for admin lookups and the nightly sync job.
 */

register_activation_hook( __FILE__, 'acme_catalog_sync_activate' );
add_action( 'acme_catalog_sync_cron', 'acme_run_catalog_sync' );

function acme_catalog_sync_activate() {
	add_option( 'acme_catalog_snapshot', array() );

	if ( ! wp_next_scheduled( 'acme_catalog_sync_cron' ) ) {
		wp_schedule_event( time(), 'twicedaily', 'acme_catalog_sync_cron' );
	}
}

function acme_run_catalog_sync() {
	$response = wp_remote_get( 'https://catalog.acme-example.com/api/v1/export' );

	if ( is_wp_error( $response ) ) {
		return;
	}

	$catalog = json_decode( wp_remote_retrieve_body( $response ), true );

	if ( ! is_array( $catalog ) ) {
		return;
	}

	update_option( 'acme_catalog_snapshot', $catalog );
	update_option( 'acme_catalog_last_synced', time() );
}
```

## Scope

Static review of the code shown. Name any measurement (`wp option list
--autoload=on`, an option-size query, or a Site Health check) that would
still be needed to confirm a finding. Do not claim a specific WordPress
version's autoload default without checking the running version.
