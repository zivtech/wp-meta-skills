<?php
/**
 * Contact-form renderer for Acme Forms (design §5 row 13).
 *
 * Golden `render_shortcode()` calls `$instance->render_fields()`
 * (line ~41 in the design's narrative). The fixture's seed renames that
 * call site to `render_feilds()` — a method this class does not define —
 * which fatals with "Call to undefined method Acme_Forms::render_feilds()".
 */

defined( 'ABSPATH' ) || exit;

class Acme_Forms {

	/**
	 * Shortcode entry point: [acme_contact_form].
	 *
	 * @return string
	 */
	public static function render_shortcode() {
		$instance = new self();
		return $instance->render_fields();
	}

	/**
	 * Renders the form markup: a title (from the `acme_forms_title`
	 * option), name/email fields, and a real wp_nonce_field() — not a
	 * static nonce string, so the dynamic probe (design finding 4) can
	 * tell a live render from transcribed markup.
	 *
	 * @return string
	 */
	public function render_fields() {
		$title = get_option( 'acme_forms_title', 'Get in touch' );
		ob_start();
		?>
		<div class="acme-form">
			<h2 class="acme-form-title"><?php echo esc_html( $title ); ?></h2>
			<form class="acme-form" method="post">
				<input type="text" name="acme_name" />
				<input type="email" name="acme_email" />
				<?php wp_nonce_field( 'acme_forms_submit', 'acme_forms_nonce' ); ?>
			</form>
		</div>
		<?php
		return ob_get_clean();
	}
}
