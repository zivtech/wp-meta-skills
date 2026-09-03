<?php
/**
 * Events listing template (design §11.2/§11.5).
 *
 * Renders `<ul class="acme-events">` with one `<li>` per event, each
 * carrying an `<a>` to the event and a `<time class="acme-date">` whose
 * text is acme_format_date() of the event's `acme_event_date` meta. This
 * is a real, dynamic WP_Query render — not static markup — which is what
 * the dynamic nonce probe (design finding 4) verifies: a newly created
 * event must appear here without any code change.
 */

defined( 'ABSPATH' ) || exit;

get_header();

$acme_events_query = new WP_Query(
	array(
		'post_type'      => 'event',
		'post_status'    => 'publish',
		'posts_per_page' => -1,
		'meta_key'       => 'acme_event_date',
		'orderby'        => 'meta_value',
		'order'          => 'ASC',
	)
);
?>
<ul class="acme-events">
<?php foreach ( $acme_events_query->posts as $acme_event ) : ?>
	<?php
	$acme_raw_date   = get_post_meta( $acme_event->ID, 'acme_event_date', true );
	$acme_event_date = acme_format_date( $acme_raw_date );
	?>
	<li>
		<a href="<?php echo esc_url( get_permalink( $acme_event ) ); ?>"><?php echo esc_html( get_the_title( $acme_event ) ); ?></a>
		<time class="acme-date"><?php echo esc_html( $acme_event_date ); ?></time>
	</li>
<?php endforeach; ?>
</ul>
<?php
get_footer();
