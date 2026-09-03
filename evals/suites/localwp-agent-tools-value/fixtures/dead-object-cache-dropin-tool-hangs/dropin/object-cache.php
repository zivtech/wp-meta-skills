<?php
/**
 * Stale object-cache.php drop-in left by a previous host (design §5 row 12,
 * fixture dead-object-cache-dropin-tool-hangs). This is the FAULT itself —
 * it does not exist in the golden site; seed.sh installs a copy of this
 * file at wp-content/object-cache.php.
 *
 * Drop-ins load unconditionally from wp-settings.php — WP-CLI's
 * --skip-plugins does not skip them (design §1, get_site_info's blind
 * spot). On wp_cache_init() this backend tries to reach a Redis instance
 * that no longer exists at this host, retries five times with backoff, and
 * falls silently back to WordPress's built-in in-memory cache. It never
 * logs anything, so nothing in error.log points at it.
 *
 * License: GPL-2.0-or-later.
 */

defined( 'ABSPATH' ) || exit;

/**
 * wp_cache_init() is the drop-in contract every WP_Object_Cache-alike must
 * satisfy; WordPress calls it once, early, instead of instantiating its own
 * WP_Object_Cache.
 */
function wp_cache_init() {
	global $wp_object_cache;
	$wp_object_cache = new Acme_Dead_Cache_Backend();
}

/**
 * A cache backend that spends real wall-clock time discovering its
 * upstream is gone before falling back to an in-memory WP_Object_Cache.
 * Every public cache function below delegates to the fallback once
 * construction (and its backoff) has finished.
 */
class Acme_Dead_Cache_Backend {

	/** @var string */
	private $host = '127.0.0.1';

	/** @var int */
	private $port = 6379;

	/** @var int seconds per connection attempt */
	private $connect_timeout = 2;

	/** @var int[] seconds to sleep between retries: 5+10+20+40 = 75s total */
	private $backoff_seconds = array( 5, 10, 20, 40 );

	/** @var WP_Object_Cache */
	private $fallback;

	public function __construct() {
		$this->fallback = new WP_Object_Cache();
		$this->connect_with_backoff();
	}

	private function connect_with_backoff() {
		if ( $this->try_connect() ) {
			return;
		}
		foreach ( $this->backoff_seconds as $seconds ) {
			sleep( $seconds );
			if ( $this->try_connect() ) {
				return;
			}
		}
		// Every attempt failed; fall back silently. Nothing is logged here
		// on purpose — this is the fixture's whole point.
	}

	private function try_connect() {
		$connection = @fsockopen( $this->host, $this->port, $errno, $errstr, $this->connect_timeout );
		if ( $connection ) {
			fclose( $connection );
			return true;
		}
		return false;
	}

	public function __call( $name, $arguments ) {
		return call_user_func_array( array( $this->fallback, $name ), $arguments );
	}
}
