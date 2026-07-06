"""Tests for the WordPress executor artifact certification pipeline."""

import sys
from pathlib import Path
from types import SimpleNamespace


HARNESS = Path(__file__).resolve().parent.parent
REPO = HARNESS.parents[1]
sys.path.insert(0, str(HARNESS))

import certify_wordpress_executor_artifact as certifier


GOOD_PLUGIN_PACKET = """\
## Spec Conformance
Implements the approved plugin packet with no storage or routing beyond scope.

## Generated File Map
- `acme-runtime/acme-runtime.php`
- `acme-runtime/readme.txt`

## Implementation Packets
### acme-runtime/acme-runtime.php
```php
<?php
/**
 * Plugin Name: Acme Runtime
 * Description: Minimal runtime fixture.
 * Version: 0.1.0
 * Requires PHP: 8.1
 * Text Domain: acme-runtime
 *
 * @package AcmeRuntime
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

register_activation_hook( __FILE__, 'acme_runtime_activate' );
register_deactivation_hook( __FILE__, 'acme_runtime_deactivate' );

function acme_runtime_activate() {
    add_option( 'acme_runtime_mode', 'safe' );
}

function acme_runtime_deactivate() {
    delete_transient( 'acme_runtime_preview' );
}

add_action( 'admin_init', 'acme_runtime_register_settings' );
function acme_runtime_register_settings() {
    register_setting(
        'acme_runtime',
        'acme_runtime_mode',
        array(
            'sanitize_callback' => 'sanitize_key',
            'default'           => 'safe',
        )
    );
}

function acme_runtime_render_status() {
    if ( ! current_user_can( 'manage_options' ) ) {
        return;
    }
    echo esc_html( get_option( 'acme_runtime_mode', 'safe' ) );
}
```

### acme-runtime/readme.txt
```txt
=== Acme Runtime ===
Contributors: acme
Requires at least: 6.5
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html
```

## Security Notes
Admin display is guarded by `current_user_can()` and escaped with `esc_html()`.
Settings use `register_setting()` with `sanitize_key()`. Future forms must add
`check_admin_referer()` before writes.

## Deviation Log
No deviations.

## Verification Notes
Run PHPCS/WPCS, PHPUnit where tests exist, WP-CLI smoke commands, and Plugin Check.

## Critic Handoff
Send to `wordpress-security-critic` and `wordpress-critic`.
"""


BAD_PLUGIN_PACKET = """\
## Spec Conformance
Maybe make a plugin.

## Implementation Packets
Use WordPress APIs and run tests.
"""


BAD_WPCS_SHAPE_PACKET = """\
## Spec Conformance
Implements the approved plugin packet with no storage or routing beyond scope.

## Generated File Map
- `acme-runtime/acme-runtime.php`
- `acme-runtime/readme.txt`

## Implementation Packets
### acme-runtime/acme-runtime.php
```php
<?php
/**
 * Plugin Name: Acme Runtime
 * Description: Minimal runtime fixture.
 * Version: 0.1.0
 * Requires PHP: 8.1
 * Text Domain: acme-runtime
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

function acme_runtime_render_status() {
    if ( ! current_user_can( 'manage_options' ) ) {
        return;
    }
    $response = [
        'mode' => get_option( 'acme_runtime_mode', 'safe' ),
    ];
    echo esc_html( $response['mode'] );
}
```

### acme-runtime/readme.txt
```txt
=== Acme Runtime ===
Contributors: acme
Requires at least: 6.5
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html
```

## Security Notes
Admin display is guarded by `current_user_can()` and escaped with `esc_html()`.
Verification must include PHPCS/WPCS, PHPUnit where tests exist, WP-CLI smoke commands, and Plugin Check.

## Deviation Log
No deviations.

## Verification Notes
Run PHPCS/WPCS, PHPUnit where tests exist, WP-CLI smoke commands, and Plugin Check. These commands were not run while drafting this packet.

## Critic Handoff
Send to `wordpress-security-critic` and `wordpress-critic`.
"""


GOOD_BLOCK_PACKET = """\
## Spec Conformance
Implements the approved block packet with `block.json`, `@wordpress/scripts`,
and a wrapper handoff that will call `register_block_type()`.
Generated paths: `package.json`, `blocks/runtime-card/block.json`,
`blocks/runtime-card/index.js`, and `blocks/runtime-card/render.php`.

## Generated Block Files
### package.json
```json
{
  "scripts": {
    "build": "wp-scripts build"
  },
  "devDependencies": {
    "@wordpress/scripts": "^30.0.0"
  }
}
```

### blocks/runtime-card/block.json
```json
{
  "apiVersion": 3,
  "name": "acme/runtime-card",
  "title": "Runtime Card",
  "category": "widgets",
  "editorScript": "file:./index.js",
  "render": "file:./render.php"
}
```

### blocks/runtime-card/index.js
```js
window.wp.blocks.registerBlockType( 'acme/runtime-card', {
  edit: function () {
    return window.wp.element.createElement( 'p', {}, 'Runtime block smoke' );
  },
  save: function () {
    return null;
  }
} );
```

### blocks/runtime-card/render.php
```php
<?php
?>
<div <?php echo wp_kses_data( get_block_wrapper_attributes() ); ?>>
	<?php echo esc_html__( 'Runtime block smoke', 'acme-runtime-card' ); ?>
</div>
```

## Compatibility Notes
Dynamic rendering requires a wrapper plugin or host plugin to call `register_block_type()`.

## Security Performance And Accessibility Notes
No SQL, REST, AJAX, uploads, or remote calls. Output is escaped with `esc_html__()`
and wrapper attributes are constrained through `wp_kses_data()`.

## Deviation Log
No deviations.

## Verification Notes
Run npm build, block validation, editor smoke, and frontend smoke.

## Critic Handoff
Send to `wordpress-critic` and `wordpress-performance-critic`.
"""


def args(packet, out_dir, result_dir=None, overwrite=False, executor="plugin"):
    return SimpleNamespace(
        executor=executor,
        packet=packet,
        out_dir=out_dir,
        overwrite=overwrite,
        result_dir=result_dir,
        profile="static",
        require_tool=[],
        wp_root=None,
        wp_env_root=None,
        plugin_check_require=None,
        timeout_sec=5,
    )


def test_certifier_passes_materializable_plugin_packet(tmp_path):
    packet = tmp_path / "candidate-output.md"
    packet.write_text(GOOD_PLUGIN_PACKET, encoding="utf-8")
    out_dir = tmp_path / "generated"
    result_dir = tmp_path / "result"

    result = certifier.certify_executor_artifact(args(packet, out_dir, result_dir))

    assert result["status"] == "pass"
    assert result["packet_gate"]["pass"] is True
    assert result["materialization_gate"]["pass"] is True
    assert result["artifact_gate"]["status"] == "pass"
    assert (out_dir / "acme-runtime" / "acme-runtime.php").exists()
    assert (result_dir / "certification.json").exists()
    assert (result_dir / "scorecard.md").exists()


def test_certifier_stops_before_materialization_when_packet_contract_fails(tmp_path):
    packet = tmp_path / "candidate-output.md"
    packet.write_text(BAD_PLUGIN_PACKET, encoding="utf-8")
    out_dir = tmp_path / "generated"

    result = certifier.certify_executor_artifact(args(packet, out_dir))

    assert result["status"] == "fail"
    assert result["packet_gate"]["pass"] is False
    assert result["materialization_gate"]["status"] == "skip"
    assert result["artifact_gate"] is None
    assert not out_dir.exists()


def test_certifier_writes_repair_prompt_for_artifact_failures(tmp_path):
    packet = tmp_path / "candidate-output.md"
    packet.write_text(BAD_WPCS_SHAPE_PACKET, encoding="utf-8")
    out_dir = tmp_path / "generated"
    result_dir = tmp_path / "result"

    result = certifier.certify_executor_artifact(args(packet, out_dir, result_dir))

    assert result["status"] == "fail"
    assert result["packet_gate"]["pass"] is True
    assert result["materialization_gate"]["pass"] is True
    assert any(item["id"] == "php_wpcs_shape_heuristics" for item in result["feedback"])
    repair_prompt = (result_dir / "repair-prompt.md").read_text(encoding="utf-8")
    scorecard = (result_dir / "scorecard.md").read_text(encoding="utf-8")
    assert "php_wpcs_shape_heuristics" in repair_prompt
    assert "Return the full corrected packet only" in repair_prompt
    assert "## Saved Packet To Revise" in repair_prompt
    assert "````markdown\n" in repair_prompt
    assert "### acme-runtime/acme-runtime.php" in repair_prompt
    assert "Plugin Name: Acme Runtime" in repair_prompt
    assert repair_prompt.rstrip().endswith("````")
    assert "php_wpcs_shape_heuristics" in scorecard


def test_repository_golden_plugin_packet_certifies(tmp_path):
    packet = REPO / "evals" / "suites" / "wordpress-plugin-executor" / "examples" / "smoke-wordpress-v1.materializable-packet.md"

    result = certifier.certify_executor_artifact(args(packet, tmp_path / "generated", tmp_path / "result"))

    assert result["status"] == "pass"
    assert result["packet"] == "evals/suites/wordpress-plugin-executor/examples/smoke-wordpress-v1.materializable-packet.md"
    assert result["materialization_gate"]["out_dir"].endswith("generated")
    assert result["artifact_gate"]["status"] == "pass"


def test_repository_golden_block_packet_certifies(tmp_path):
    packet = REPO / "evals" / "suites" / "wordpress-block-executor" / "examples" / "smoke-wordpress-v1.materializable-packet.md"

    result = certifier.certify_executor_artifact(args(packet, tmp_path / "generated-block", tmp_path / "result", executor="block"))

    assert result["status"] == "pass"
    assert result["packet"] == "evals/suites/wordpress-block-executor/examples/smoke-wordpress-v1.materializable-packet.md"
    assert result["materialization_gate"]["out_dir"].endswith("generated-block")
    assert result["artifact_gate"]["artifact_type"] == "block"
    assert result["artifact_gate"]["status"] == "pass"


def test_certifier_passes_materializable_block_packet(tmp_path):
    packet = tmp_path / "candidate-block-output.md"
    packet.write_text(GOOD_BLOCK_PACKET, encoding="utf-8")
    out_dir = tmp_path / "generated-block"
    result_dir = tmp_path / "result"

    result = certifier.certify_executor_artifact(args(packet, out_dir, result_dir, executor="block"))

    assert result["status"] == "pass"
    assert result["packet_gate"]["pass"] is True
    assert result["materialization_gate"]["pass"] is True
    assert result["artifact_gate"]["artifact_type"] == "block"
    assert result["artifact_gate"]["status"] == "pass"
    assert (out_dir / "blocks" / "runtime-card" / "block.json").exists()
    assert (out_dir / "package.json").exists()
    assert (result_dir / "certification.json").exists()
