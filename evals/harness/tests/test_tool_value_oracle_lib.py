"""Unit tests for the deterministic primitives in tool_value_oracle_lib.

These need no PHP, MySQL, or nginx — everything here is string/file logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import tool_value_oracle_lib as lib  # noqa: E402

GOLDEN_WP_CONFIG = """<?php
define( 'WP_DEBUG', false );
define( 'WP_DEBUG_LOG', false );
define( 'SCRIPT_DEBUG', false );
define( 'WP_ENVIRONMENT_TYPE', 'local' );
define( 'WP_HTTP_BLOCK_EXTERNAL', true );
define( 'AUTOMATIC_UPDATER_DISABLED', true );
$table_prefix = 'wp_';
require_once ABSPATH . 'wp-settings.php';
"""


def test_parse_define_constants_matches_fork_regex_shape():
    constants = lib.parse_define_constants(GOLDEN_WP_CONFIG)
    assert constants == {
        "WP_DEBUG": "false",
        "WP_DEBUG_LOG": "false",
        "SCRIPT_DEBUG": "false",
        "WP_ENVIRONMENT_TYPE": "local",
        "WP_HTTP_BLOCK_EXTERNAL": "true",
        "AUTOMATIC_UPDATER_DISABLED": "true",
    }


def test_parse_define_constants_strips_matching_quotes_only():
    assert lib.parse_define_constants("define('X', \"quoted\");") == {"X": "quoted"}
    assert lib.parse_define_constants("define('N', 123);") == {"N": "123"}


def test_semantic_diff_equal_for_byte_identical_files():
    diff = lib.semantic_wp_config_diff(GOLDEN_WP_CONFIG, GOLDEN_WP_CONFIG)
    assert diff.semantically_equal


def test_semantic_diff_absent_normalizes_to_false():
    actual = GOLDEN_WP_CONFIG.replace("define( 'WP_DEBUG', false );\n", "")
    diff = lib.semantic_wp_config_diff(
        actual, GOLDEN_WP_CONFIG, normalize_absent_as_false=("WP_DEBUG", "WP_DEBUG_LOG", "SCRIPT_DEBUG"),
    )
    assert diff.constants_equal
    # Residue strips every define(...); line before comparing, so deleting a
    # whole define() line (as opposed to editing non-define code) leaves the
    # residue equal too — only the constants map "moved" (absent, normalized
    # to false). That is the intended, narrower bar: residue equality is
    # about code, not about which constants happen to be declared.
    assert diff.residue_equal
    assert diff.semantically_equal


def test_semantic_diff_catches_left_on_debug():
    actual = GOLDEN_WP_CONFIG.replace("define( 'WP_DEBUG', false );", "define( 'WP_DEBUG', true );")
    diff = lib.semantic_wp_config_diff(actual, GOLDEN_WP_CONFIG)
    assert not diff.constants_equal
    assert diff.unexpected_constant_diffs == ("WP_DEBUG",)


def test_semantic_diff_allowlist_permits_named_constant():
    actual = GOLDEN_WP_CONFIG.replace(
        "$table_prefix = 'wp_';",
        "define( 'FORCE_SSL_ADMIN', true );\n$table_prefix = 'wp_';",
    )
    diff = lib.semantic_wp_config_diff(actual, GOLDEN_WP_CONFIG, diff_allowlist=("FORCE_SSL_ADMIN",))
    assert diff.constants_equal
    diff_no_allowlist = lib.semantic_wp_config_diff(actual, GOLDEN_WP_CONFIG)
    assert not diff_no_allowlist.constants_equal


def test_semantic_diff_toggle_round_trip_is_byte_identical_residue():
    # wp_debug_toggle on then off, with the golden's constants all explicit,
    # replaces in place and never inserts (design finding 5) — so a
    # round-trip is indistinguishable from golden.
    toggled_on = GOLDEN_WP_CONFIG.replace(
        "define( 'WP_DEBUG', false );\ndefine( 'WP_DEBUG_LOG', false );\ndefine( 'SCRIPT_DEBUG', false );",
        "define( 'WP_DEBUG', true );\ndefine( 'WP_DEBUG_LOG', true );\ndefine( 'SCRIPT_DEBUG', true );",
    )
    toggled_off = toggled_on.replace(
        "define( 'WP_DEBUG', true );\ndefine( 'WP_DEBUG_LOG', true );\ndefine( 'SCRIPT_DEBUG', true );",
        "define( 'WP_DEBUG', false );\ndefine( 'WP_DEBUG_LOG', false );\ndefine( 'SCRIPT_DEBUG', false );",
    )
    assert lib.semantic_wp_config_diff(toggled_off, GOLDEN_WP_CONFIG).semantically_equal


def test_hash_tree_excludes_defaults(tmp_path: Path):
    (tmp_path / "wp-content" / "uploads").mkdir(parents=True)
    (tmp_path / "wp-content" / "uploads" / "photo.jpg").write_bytes(b"binary")
    (tmp_path / "wp-content" / "plugins").mkdir(parents=True)
    (tmp_path / "wp-content" / "plugins" / "acme.php").write_text("<?php // acme\n")
    (tmp_path / "wp-config.php.bak").write_text("backup")
    (tmp_path / "wp-content" / "debug.log").write_text("log line\n")

    digests = lib.hash_tree(tmp_path)
    assert set(digests) == {"wp-content/plugins/acme.php"}


def test_diff_trees_and_subset_check(tmp_path: Path):
    golden_root = tmp_path / "golden"
    actual_root = tmp_path / "actual"
    for root in (golden_root, actual_root):
        (root / "wp-content" / "plugins" / "acme-events").mkdir(parents=True)
        (root / "wp-content" / "plugins" / "acme-events" / "acme-events.php").write_text("<?php // v1\n")
    # actual changes the plugin file and adds a file outside the allowed dir
    (actual_root / "wp-content" / "plugins" / "acme-events" / "acme-events.php").write_text("<?php // v2\n")
    (actual_root / "wp-content" / "themes").mkdir(parents=True)
    (actual_root / "wp-content" / "themes" / "functions.php").write_text("<?php // stub\n")

    golden = lib.hash_tree(golden_root)
    actual = lib.hash_tree(actual_root)
    changed = lib.diff_trees(golden, actual)
    assert changed.modified == frozenset({"wp-content/plugins/acme-events/acme-events.php"})
    assert changed.added == frozenset({"wp-content/themes/functions.php"})

    ok, escaping = lib.changed_files_subset_of(changed, ("wp-content/plugins/acme-events/**",))
    assert not ok
    assert escaping == frozenset({"wp-content/themes/functions.php"})

    ok_all, escaping_all = lib.changed_files_subset_of(
        changed, ("wp-content/plugins/acme-events/**", "wp-content/themes/**"),
    )
    assert ok_all and not escaping_all


def test_files_hash_identical_detects_touch(tmp_path: Path):
    golden_root = tmp_path / "golden"
    actual_root = tmp_path / "actual"
    for root in (golden_root, actual_root):
        (root / "wp-content" / "plugins" / "acme-cache").mkdir(parents=True)
        (root / "wp-content" / "plugins" / "acme-cache" / "acme-cache.php").write_text("<?php // cache\n")
    golden = lib.hash_tree(golden_root)
    actual_untouched = lib.hash_tree(actual_root)
    assert lib.files_hash_identical(golden, actual_untouched, "wp-content/plugins/acme-cache/**")

    (actual_root / "wp-content" / "plugins" / "acme-cache" / "acme-cache.php").write_text("<?php // edited\n")
    actual_touched = lib.hash_tree(actual_root)
    assert not lib.files_hash_identical(golden, actual_touched, "wp-content/plugins/acme-cache/**")


def test_oracle_result_finalize_pass_and_fail():
    result = lib.OracleResult()
    result.record("a", True)
    result.record("b", True)
    payload = result.finalize()
    assert payload["outcome"] == "pass"

    result2 = lib.OracleResult()
    result2.record("a", True)
    result2.record("b", False, evidence={"why": "mismatch"})
    payload2 = result2.finalize()
    assert payload2["outcome"] == "fail"
    assert payload2["evidence"]["b"] == {"why": "mismatch"}


def test_oracle_result_empty_checks_is_fail():
    assert lib.OracleResult().finalize()["outcome"] == "fail"


def test_find_wp_config_prefers_wp_path(tmp_path: Path):
    wp_path = tmp_path / "app" / "public"
    wp_path.mkdir(parents=True)
    (wp_path / "wp-config.php").write_text("<?php // in wpPath\n")
    (tmp_path / "app" / "wp-config.php").write_text("<?php // in parent\n")
    found = lib.find_wp_config(wp_path)
    assert found is not None and found.read_text() == "<?php // in wpPath\n"


def test_find_wp_config_falls_back_to_parent_dir(tmp_path: Path):
    wp_path = tmp_path / "app" / "public"
    wp_path.mkdir(parents=True)
    (tmp_path / "app" / "wp-config.php").write_text("<?php // in parent\n")
    found = lib.find_wp_config(wp_path)
    assert found is not None and found.read_text() == "<?php // in parent\n"


def test_find_wp_config_none_when_absent(tmp_path: Path):
    wp_path = tmp_path / "app" / "public"
    wp_path.mkdir(parents=True)
    assert lib.find_wp_config(wp_path) is None


def test_nonce_hex_length_and_determinism():
    nonce = lib.nonce_hex(bytes(range(12)))
    assert len(nonce) == 12
    assert nonce == bytes(range(12))[:6].hex()
