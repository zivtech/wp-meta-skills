<?php
/**
 * Golden wp-config.php for fixture dead-object-cache-dropin-tool-hangs
 * (design §2.4). No disable constant for the drop-in — that would be a
 * legitimate fix and would change the allowed-changes set (metadata.yaml
 * `seed.no_disable_constant: true`).
 */

define( 'WP_DEBUG', false );
define( 'WP_DEBUG_LOG', false );
define( 'SCRIPT_DEBUG', false );
define( 'WP_ENVIRONMENT_TYPE', 'local' );
define( 'WP_HTTP_BLOCK_EXTERNAL', true );
define( 'AUTOMATIC_UPDATER_DISABLED', true );

$table_prefix = 'wp_';

/* That's all, stop editing! Happy publishing. */

require_once ABSPATH . 'wp-settings.php';
