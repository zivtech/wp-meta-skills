<?php
/**
 * Plugin Name: Acme Events
 * Description: Tiny GPL fixture plugin for the localwp-agent-tools-value
 *              eval, fixture fatal-undefined-function-page-scoped (design
 *              §11.2). Registers the `event` CPT and a shortcode-free
 *              template that lists events on the "Events" page.
 * Version:     1.0.0
 * License:     GPL-2.0-or-later
 *
 * This file is the golden (unfaulted) source of truth. seed.sh mutates a
 * copy of it to introduce the fixture's fault; reference-fix.sh restores
 * this exact shape.
 */

defined( 'ABSPATH' ) || exit;

require_once __DIR__ . '/includes/formatting.php';

add_action( 'init', 'acme_events_register_cpt' );

/**
 * Registers the `event` custom post type used by the events listing.
 */
function acme_events_register_cpt() {
	register_post_type(
		'event',
		array(
			'label'    => 'Events',
			'public'   => true,
			'show_ui'  => true,
			'supports' => array( 'title' ),
			'rewrite'  => array( 'slug' => 'events' ),
		)
	);
}

add_filter( 'template_include', 'acme_events_template_include' );

/**
 * Swaps in the events-list template for the site's "Events" page.
 *
 * @param string $template Template path WordPress resolved.
 * @return string
 */
function acme_events_template_include( $template ) {
	if ( is_page( 'events' ) ) {
		return __DIR__ . '/templates/events-list.php';
	}
	return $template;
}
