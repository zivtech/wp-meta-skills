"""Tests for materializing saved WordPress executor packets into files."""

import json
import sys
from pathlib import Path


HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import materialize_wordpress_executor_packet as materializer


GOOD_PLUGIN_PACKET = """\
## Spec Conformance
Implements the approved packet.

## Generated File Map
- `acme-runtime/acme-runtime.php`
- `acme-runtime/readme.txt`

## Implementation Packets
### acme-runtime/acme-runtime.php
```php
<?php
/**
 * Plugin Name: Acme Runtime
 */
add_action( 'init', 'acme_runtime_boot' );
function acme_runtime_boot() {
    register_setting( 'acme_runtime', 'acme_runtime_mode' );
}
```

### acme-runtime/readme.txt
```txt
=== Acme Runtime ===
Contributors: acme
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
```

## Security Notes
Use `current_user_can()` and `check_admin_referer()`.

## Deviation Log
No deviations.

## Verification Notes
Run PHPCS/WPCS, PHPUnit, WP-CLI smoke commands, and Plugin Check.

## Critic Handoff
Send to `wordpress-security-critic` and `wordpress-critic`.
"""


GOOD_BLOCK_PACKET = """\
## Spec Conformance
Implements the approved block packet with `block.json`, `@wordpress/scripts`,
and a future plugin handoff that will call `register_block_type()`.
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
echo wp_kses_data( get_block_wrapper_attributes() );
```

## Compatibility Notes
Uses dynamic rendering and requires the wrapper plugin to call `register_block_type()`.

## Security Performance And Accessibility Notes
No SQL, REST, AJAX, uploads, or remote calls. Dynamic output must use escaping.

## Deviation Log
No deviations.

## Verification Notes
Run npm build, block validation, editor smoke, and frontend smoke.

## Critic Handoff
Send to `wordpress-critic` and `wordpress-performance-critic`.
"""


def test_good_plugin_packet_materializes_files(tmp_path):
    out_dir = tmp_path / "artifact"

    result = materializer.materialize_packet("plugin", GOOD_PLUGIN_PACKET, out_dir)

    assert result["pass"] is True
    assert {item["path"] for item in result["written"]} == {
        "acme-runtime/acme-runtime.php",
        "acme-runtime/readme.txt",
    }
    assert (out_dir / "acme-runtime" / "acme-runtime.php").read_text(encoding="utf-8").startswith("<?php\n")
    assert "Stable tag" in (out_dir / "acme-runtime" / "readme.txt").read_text(encoding="utf-8")


def test_plugin_packet_materializes_phpunit_xml(tmp_path):
    packet = GOOD_PLUGIN_PACKET.replace(
        "- `acme-runtime/readme.txt`",
        "- `acme-runtime/readme.txt`\n- `acme-runtime/phpunit.xml`",
    ).replace(
        "### acme-runtime/readme.txt",
        """### acme-runtime/phpunit.xml
```xml
<?xml version="1.0" encoding="UTF-8"?>
<phpunit>
  <testsuites>
    <testsuite name="unit">
      <directory>tests</directory>
    </testsuite>
  </testsuites>
</phpunit>
```

### acme-runtime/readme.txt""",
    )
    out_dir = tmp_path / "artifact"

    result = materializer.materialize_packet("plugin", packet, out_dir)

    assert result["pass"] is True
    assert "acme-runtime/phpunit.xml" in {item["path"] for item in result["written"]}
    assert "<phpunit>" in (out_dir / "acme-runtime" / "phpunit.xml").read_text(encoding="utf-8")


def test_good_block_packet_materializes_block_files(tmp_path):
    out_dir = tmp_path / "artifact"

    result = materializer.materialize_packet("block", GOOD_BLOCK_PACKET, out_dir)

    assert result["pass"] is True
    assert {item["path"] for item in result["written"]} == {
        "package.json",
        "blocks/runtime-card/block.json",
        "blocks/runtime-card/index.js",
        "blocks/runtime-card/render.php",
    }
    assert json_loads(out_dir / "blocks" / "runtime-card" / "block.json")["name"] == "acme/runtime-card"
    assert "wp-scripts build" in (out_dir / "package.json").read_text(encoding="utf-8")


def json_loads(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_unsafe_path_fails_without_writing_files(tmp_path):
    packet = GOOD_PLUGIN_PACKET.replace("### acme-runtime/readme.txt", "### ../evil.php")
    out_dir = tmp_path / "artifact"

    result = materializer.materialize_packet("plugin", packet, out_dir)

    assert result["pass"] is False
    assert not list(out_dir.rglob("*"))
    assert "path traversal" in result["issues"][0]["detail"]


def test_duplicate_path_fails(tmp_path):
    packet = GOOD_PLUGIN_PACKET.replace("### acme-runtime/readme.txt", "### acme-runtime/acme-runtime.php")

    result = materializer.materialize_packet("plugin", packet, tmp_path / "artifact")

    assert result["pass"] is False
    assert any("duplicate generated file path" in issue["detail"] for issue in result["issues"])


def test_output_directory_must_be_empty_unless_overwrite_is_set(tmp_path):
    out_dir = tmp_path / "artifact"
    out_dir.mkdir()
    (out_dir / "existing.txt").write_text("keep me", encoding="utf-8")

    blocked = materializer.materialize_packet("plugin", GOOD_PLUGIN_PACKET, out_dir)

    assert blocked["pass"] is False
    assert (out_dir / "existing.txt").exists()

    overwritten = materializer.materialize_packet("plugin", GOOD_PLUGIN_PACKET, out_dir, overwrite=True)

    assert overwritten["pass"] is True
    assert not (out_dir / "existing.txt").exists()
    assert (out_dir / "acme-runtime" / "acme-runtime.php").exists()


def test_blueprint_packet_materializes_to_blueprint_json(tmp_path):
    packet = """\
## Input Summary
Disposable Playground repro.

## Generated Blueprint
```json
{
  "landingPage": "/wp-admin/",
  "preferredVersions": {"php": "8.2", "wp": "latest"},
  "steps": [{"step": "login", "username": "admin", "password": "password"}]
}
```

## Provenance Notes
Synthetic only.

## Safety And Determinism Notes
Reset between runs.

## Deviation Log
No deviations.

## Verification Notes
Run Blueprint schema validation, Playground launch, reset, and smoke checks.

## Critic Handoff
Send to `wordpress-critic`.
"""
    out_dir = tmp_path / "blueprint-artifact"

    result = materializer.materialize_packet("blueprint", packet, out_dir)

    assert result["pass"] is True
    assert result["written"] == [{"bytes": (out_dir / "blueprint.json").stat().st_size, "path": "blueprint.json"}]
    assert '"landingPage": "/wp-admin/"' in (out_dir / "blueprint.json").read_text(encoding="utf-8")


def test_heading_without_immediate_fence_fails(tmp_path):
    packet = GOOD_PLUGIN_PACKET.replace(
        "### acme-runtime/readme.txt\n```txt",
        "### acme-runtime/readme.txt\nThis prose makes the file non-materializable.\n```txt",
    )

    result = materializer.materialize_packet("plugin", packet, tmp_path / "artifact")

    assert result["pass"] is False
    assert any("no fenced code block found" in issue["detail"] for issue in result["issues"])
