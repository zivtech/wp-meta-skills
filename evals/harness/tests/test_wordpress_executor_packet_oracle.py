"""Tests for the deterministic WordPress executor packet oracle."""

import sys
from pathlib import Path


HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import validate_wordpress_executor_packet as oracle


GOOD_PLUGIN_PACKET = """\
## Spec Conformance
Implements the approved plugin packet and does not invent storage.

## Generated File Map
- `acme-members/acme-members.php`
- `acme-members/includes/Admin/Settings.php`
- `acme-members/tests/test-settings.php`
- `acme-members/readme.txt`

## Implementation Packets
Use `register_activation_hook()`, `register_deactivation_hook()`, `register_setting()`,
`current_user_can()`, `sanitize_key()`, `sanitize_text_field()`, `esc_html()`, and
`wp_kses_post()` in the generated files.

## Security Notes
No secrets are embedded. Admin actions use `current_user_can()` and `check_admin_referer()`.

## Deviation Log
No deviations.

## Verification Notes
Run PHPCS/WPCS, PHPUnit, WP-CLI smoke commands, and Plugin Check before handoff.

## Critic Handoff
Send to `wordpress-security-critic` and `wordpress-critic`.
"""


BAD_PLUGIN_PACKET = """\
## Plan
Make a plugin with good security.

## Implementation
Use WordPress APIs, use capabilities, use nonces, use escaping, run tests, and cache it.
"""


GOOD_BLUEPRINT_PACKET = """\
## Input Summary
Disposable WordPress Playground repro for a plugin smoke test.

## Generated Blueprint
```json
{
  "landingPage": "/wp-admin/",
  "preferredVersions": {"php": "8.2", "wp": "latest"},
  "steps": [
    {"step": "login", "username": "admin", "password": "password"}
  ]
}
```

## Provenance Notes
No production endpoints. Blueprint and Playground sources are synthetic.

## Safety And Determinism Notes
Reset the Playground between runs.

## Deviation Log
No deviations.

## Verification Notes
Run Blueprint schema validation, launch in Playground, reset, and smoke the landing page.

## Critic Handoff
Send to `wordpress-critic`.
"""


BAD_BLUEPRINT_PACKET = """\
## Input Summary
Demo.

## Generated Blueprint
```json
{"steps": [
```

## Provenance Notes
None.

## Safety And Determinism Notes
None.

## Deviation Log
None.

## Verification Notes
Open it.

## Critic Handoff
Ask someone.
"""


def test_good_plugin_packet_passes():
    result = oracle.validate_packet(GOOD_PLUGIN_PACKET, "plugin")
    assert result["pass"] is True
    assert result["score"] == 1.0


def test_plugin_packet_accepts_runnable_wp_commands_as_wp_cli_verification():
    packet = GOOD_PLUGIN_PACKET.replace(
        "Run PHPCS/WPCS, PHPUnit, WP-CLI smoke commands, and Plugin Check before handoff.",
        "Run PHPCS/WPCS, PHPUnit, and Plugin Check before handoff.\n\n```bash\nwp plugin activate acme-members\nwp plugin check acme-members\n```",
    )

    result = oracle.validate_packet(packet, "plugin")

    assert result["pass"] is True


def test_bad_plugin_packet_fails_with_missing_contracts():
    result = oracle.validate_packet(BAD_PLUGIN_PACKET, "plugin")
    assert result["pass"] is False
    failed = {check["id"] for check in result["checks"] if not check["passed"]}
    assert {"required_headings", "packet_only_output", "file_map", "exact_surfaces", "verification_oracles", "critic_handoff"} <= failed


def test_good_blueprint_packet_passes_and_parses_json():
    result = oracle.validate_packet(GOOD_BLUEPRINT_PACKET, "blueprint")
    assert result["pass"] is True
    assert any(check["id"] == "blueprint_json" and check["passed"] for check in result["checks"])


def test_bad_blueprint_packet_fails_json_and_handoff():
    result = oracle.validate_packet(BAD_BLUEPRINT_PACKET, "blueprint")
    assert result["pass"] is False
    failed = {check["id"] for check in result["checks"] if not check["passed"]}
    assert {"blueprint_json", "verification_oracles", "critic_handoff"} <= failed


def test_phase_transcript_fails_packet_only_gate():
    packet = """\
Generating the implementation packet.

## Phase 1
Reviewing the spec.

## Spec Conformance
Looks good.

## Generated File Map
- `acme/acme.php`
- `acme/readme.txt`

## Implementation Packets
Use `current_user_can()`, `register_setting()`, `sanitize_key()`, `esc_html()`, Plugin Check, PHPCS, PHPUnit, and WP-CLI.

## Security Notes
No endpoints.

## Deviation Log
No deviations.

## Verification Notes
Run PHPCS/WPCS, PHPUnit, WP-CLI smoke commands, and Plugin Check.

## Critic Handoff
Send to `wordpress-security-critic` and `wordpress-critic`.
"""

    result = oracle.validate_packet(packet, "plugin")
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert "packet_only_output" in failed


def test_table_file_map_counts_code_spanned_paths():
    packet = GOOD_PLUGIN_PACKET.replace(
        "- `acme-members/acme-members.php`\n- `acme-members/includes/Admin/Settings.php`\n- `acme-members/tests/test-settings.php`\n- `acme-members/readme.txt`",
        "| File | Purpose |\n|---|---|\n| `acme-members/acme-members.php` | Bootstrap |\n| `acme-members/readme.txt` | Readme |",
    )

    result = oracle.validate_packet(packet, "plugin")

    assert result["pass"] is True
    assert any(check["id"] == "file_map" and check["passed"] for check in result["checks"])
