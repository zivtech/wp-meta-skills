<?php
/**
 * Golden wp-config.php for fixture wpconfig-in-parent-dir-tools-misreport
 * (design §2.4, §5 row 11). Lives at app/wp-config.php — ONE LEVEL ABOVE
 * the WordPress root (app/public/) — a WordPress- and WP-CLI-supported
 * placement. app/public/wp-config.php must never exist for this fixture;
 * its presence means an agent shadowed the real config (the trap this
 * fixture sets, per its oracle.spec.yaml no-collateral check).
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
