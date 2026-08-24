"""Tests for the deterministic phpcbf packet auto-fix stage.

Pure rewrite tests need no PHP toolchain; the integration tests run the real
pinned phpcbf and skip when the toolchain is unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import materialize_wordpress_executor_packet as materializer  # noqa: E402
import wp_security_gate  # noqa: E402
import wpcs_autofix  # noqa: E402


PACKET = """\
## Spec Conformance
ok

## Implementation Packets

### acme/one.php
```php
<?php
function acme_one() {
    return 1;
}
```

### acme/two.php
```php
<?php
function acme_two() {
    return 2;
}
```

### acme/readme.txt
```
=== Acme ===

## Description

Readme heading inside the fence must survive rewriting.
```

## Verification Notes
ok
"""


def _blocks(packet_text: str) -> dict[str, str]:
    parsed = materializer.sections(packet_text)
    extracted, issues = materializer.extract_file_blocks(parsed["Implementation Packets"])
    assert not issues
    return {str(path): content for path, content in extracted}


def test_rewrite_packet_splices_only_named_files():
    fixed_body = "<?php\nfunction acme_one_fixed() {\n\treturn 1;\n}\n"
    new_text, changed = wpcs_autofix.rewrite_packet(PACKET, "plugin", {"acme/one.php": fixed_body})

    assert changed == ("acme/one.php",)
    blocks = _blocks(new_text)
    assert blocks["acme/one.php"] == fixed_body
    assert blocks["acme/two.php"] == _blocks(PACKET)["acme/two.php"]
    assert "## Description" in blocks["acme/readme.txt"]
    # Everything outside the spliced fence is byte-identical.
    assert new_text.startswith(PACKET[: PACKET.index("function acme_one")])
    assert new_text.endswith(PACKET[PACKET.index("### acme/two.php"):])


def test_rewrite_packet_identical_content_is_a_no_op():
    same = _blocks(PACKET)["acme/one.php"]
    new_text, changed = wpcs_autofix.rewrite_packet(PACKET, "plugin", {"acme/one.php": same})
    assert changed == ()
    assert new_text == PACKET


def test_rewrite_packet_unknown_file_is_ignored():
    new_text, changed = wpcs_autofix.rewrite_packet(
        PACKET, "plugin", {"acme/absent.php": "<?php\n"},
    )
    assert changed == ()
    assert new_text == PACKET


TOOLCHAIN, _TOOLCHAIN_REASON = wp_security_gate.resolve_toolchain()
needs_toolchain = pytest.mark.skipif(
    TOOLCHAIN is None or not wpcs_autofix.phpcbf_path(TOOLCHAIN).exists(),
    reason="pinned phpcbf/WPCS toolchain unavailable",
)


MESSY_PACKET = PACKET.replace(
    "<?php\nfunction acme_one() {\n    return 1;\n}",
    "<?php\nfunction acme_one( $value ) {\n    if($value){\n        return true;\n    }\n    return false;\n}",
)


@needs_toolchain
def test_autofix_packet_text_fixes_wpcs_whitespace(tmp_path):
    outcome = wpcs_autofix.autofix_packet_text(MESSY_PACKET, "plugin", tmp_path, 120)

    assert outcome.changed is True
    assert "acme/one.php" in outcome.files_changed
    fixed = _blocks(outcome.packet_text)["acme/one.php"]
    assert "\tif ( $value ) {" in fixed  # tabs + WordPress spacing, per the gate's standard
    assert _blocks(outcome.packet_text)["acme/readme.txt"] == _blocks(MESSY_PACKET)["acme/readme.txt"]


@needs_toolchain
def test_autofix_packet_text_is_idempotent(tmp_path):
    first = wpcs_autofix.autofix_packet_text(MESSY_PACKET, "plugin", tmp_path / "a", 120)
    assert first.changed is True
    second = wpcs_autofix.autofix_packet_text(first.packet_text, "plugin", tmp_path / "b", 120)
    assert second.changed is False
    assert second.packet_text == first.packet_text


def test_blueprint_packets_are_left_alone(tmp_path):
    outcome = wpcs_autofix.autofix_packet_text(PACKET, "blueprint", tmp_path, 10)
    assert outcome.changed is False
    assert outcome.packet_text == PACKET
