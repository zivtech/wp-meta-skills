<?php
/**
 * Plugin Name: Acme Cache
 * Description: Haystack/red-herring plugin for fixture
 *              fatal-in-error-log-fresh-debug-log-misleads (design §5 row
 *              13). Appends one "hits/misses" line to wp-content/debug.log
 *              on every request via a `shutdown` hook, using
 *              error_log($line, 3, $path) — message type 3 writes straight
 *              to the named file and bypasses the `error_log` ini
 *              directive entirely, so this holds regardless of how Local
 *              configures that directive (design §13.2's open question
 *              does not gate this fixture).
 *
 *              PHP logs a fatal (if any) to logs/php/error.log, THEN runs
 *              shutdown functions for the same request — so after any
 *              request, including a failing one, debug.log's mtime is
 *              newer than error.log's. That ordering is the whole fixture.
 * License:     GPL-2.0-or-later
 */

defined( 'ABSPATH' ) || exit;

add_action( 'shutdown', 'acme_cache_log_stats' );

/**
 * Appends one synthetic cache-stats line to wp-content/debug.log.
 */
function acme_cache_log_stats() {
	$hits    = wp_cache_get( 'acme_cache_hits' );
	$misses  = wp_cache_get( 'acme_cache_misses' );
	$hits    = is_int( $hits ) ? $hits : 0;
	$misses  = is_int( $misses ) ? $misses : 0;
	$request = isset( $_SERVER['REQUEST_URI'] ) ? $_SERVER['REQUEST_URI'] : '';
	$line    = sprintf(
		"[%s] acme-cache: %d hits / %d misses (%s)\n",
		gmdate( 'D M d H:i:s Y' ),
		$hits,
		$misses,
		$request
	);
	error_log( $line, 3, WP_CONTENT_DIR . '/debug.log' );
}
