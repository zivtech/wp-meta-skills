<?php
/**
 * Date formatting helper for Acme Events (design §11.2/§11.3).
 *
 * Golden acme-events.php requires this file unconditionally. The fixture's
 * seed wraps that require in `if ( is_admin() )`, so on a frontend request
 * this function is never defined and templates/events-list.php's call to
 * it fatals with "Call to undefined function acme_format_date()".
 */

defined( 'ABSPATH' ) || exit;

/**
 * Formats an event's stored date (Y-m-d) as "l, F j, Y", e.g.
 * "Saturday, October 3, 2026" — the exact golden format asserted by the
 * oracle's dynamic probe and content checks.
 *
 * @param string $date Y-m-d date string from the `acme_event_date` meta.
 * @return string
 */
function acme_format_date( $date ) {
	$timestamp = strtotime( (string) $date );
	if ( false === $timestamp ) {
		return '';
	}
	return date_i18n( 'l, F j, Y', $timestamp );
}
