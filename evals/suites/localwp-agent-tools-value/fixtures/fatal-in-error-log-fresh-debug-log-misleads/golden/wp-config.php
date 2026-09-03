<?php
/**
 * Golden wp-config.php for fixture
 * fatal-in-error-log-fresh-debug-log-misleads (design §2.4).
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
