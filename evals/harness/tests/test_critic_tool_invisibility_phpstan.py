"""Unit tests for the PHPStan half of the tranche-J tool-invisibility gate.

corpus-prereg.md claims every J fixture is clean to WPCS *and PHPStan*. Only WPCS was
enforced. These pin the classification logic that now enforces the other half; the live
run against the real corpus is the gate itself.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import verify_critic_tool_invisibility as vti


def _f(identifier, message="m", line=1):
    return {"file": "x.php", "line": line, "identifier": identifier, "message": message}


def test_known_benign_identifiers_do_not_disqualify():
    findings = [_f("missingType.return"),
                _f("argument.type", "Parameter #1 $text of function esc_html expects string, mixed given."),
                _f("constant.notFound")]
    assert vti.classify_phpstan(findings) == []


def test_missing_type_prefix_covers_every_variant():
    assert vti.classify_phpstan([_f("missingType.parameter"), _f("missingType.iterableValue")]) == []


def test_the_wpdb_is_mixed_family_is_benign():
    # Verified empirically: annotating `/** @var \wpdb $wpdb */` clears these and reveals
    # nothing about the fixture's defect, so they are excerpt artifacts.
    findings = [_f("method.nonObject"), _f("encapsedStringPart.nonString")]
    assert vti.classify_phpstan(findings) == []


def test_an_unrecognised_identifier_disqualifies_by_default():
    # Default-deny is the point: a PHPStan upgrade that starts catching a J defect must
    # trip the gate rather than pass quietly the way a deny-list would let it.
    findings = [_f("deadCode.unreachable"), _f("missingType.return")]
    disq = vti.classify_phpstan(findings)
    assert [f["identifier"] for f in disq] == ["deadCode.unreachable"]


def test_a_semantic_always_true_finding_disqualifies():
    # The shape that would mean PHPStan sees a decorative capability branch.
    assert len(vti.classify_phpstan([_f("if.alwaysTrue"), _f("booleanAnd.alwaysTrue")])) == 2


def test_a_finding_with_no_identifier_disqualifies():
    assert len(vti.classify_phpstan([{"file": "x", "line": 1, "message": "?"}])) == 1


def test_the_benign_allowlist_is_configurable():
    assert vti.classify_phpstan([_f("custom.thing")], rules=(("custom.", None),)) == []


# --- the argument.type narrowing (2026-08-13) ------------------------------- #

def test_argument_type_is_benign_only_in_its_mixed_propagation_shape():
    mixed = _f("argument.type", "Parameter #1 $str of function sanitize_text_field expects string, mixed given.")
    assert vti.classify_phpstan([mixed]) == []


def test_argument_type_carrying_the_literal_string_sql_signal_disqualifies():
    """The measured hole: PHPStan's SQL-injection heuristic shares `argument.type` with
    harmless mixed-propagation. Suppressing the identifier wholesale hid it on a typed
    variant of sec-like-wildcard-no-esc-like-v1."""
    sql = _f("argument.type",
             "Parameter #1 $query of method wpdb::prepare() expects literal-string, "
             "non-falsy-string given.")
    assert vti.classify_phpstan([sql]) == [sql]


def test_argument_type_with_a_nullable_mismatch_disqualifies():
    nullable = _f("argument.type",
                  "Parameter #1 $input_list of function wp_list_pluck expects array, "
                  "array<array<mixed>|stdClass>|null given.")
    assert len(vti.classify_phpstan([nullable])) == 1


def test_undefined_symbol_identifiers_are_not_allowlisted():
    """A typo'd hook callback is a silent no-op and a real defect class, so these must
    surface for triage rather than being pre-approved."""
    findings = [_f("function.notFound", "Function acme_typoed() not found."),
                _f("class.notFound", "Class Acme_Missing not found.")]
    assert len(vti.classify_phpstan(findings)) == 2


def test_is_benign_requires_both_identifier_and_message_to_match():
    rules = (("argument.type", "mixed given"),)
    assert vti.is_benign(_f("argument.type", "... mixed given."), rules)
    assert not vti.is_benign(_f("argument.type", "... literal-string given."), rules)
    assert not vti.is_benign(_f("other.rule", "... mixed given."), rules)


def test_parse_phpstan_json_flattens_per_file_messages():
    payload = ('{"files": {"/tmp/a.php": {"messages": ['
               '{"line": 12, "identifier": "argument.type", "message": "boom"}]}}}')
    findings, err = vti.parse_phpstan_json(payload)
    assert err == ""
    assert findings == [{"file": "/tmp/a.php", "line": 12,
                         "identifier": "argument.type", "message": "boom"}]


def test_parse_phpstan_json_surfaces_toplevel_errors_as_disqualifying():
    # An analysis crash must not read as "no findings, therefore invisible".
    findings, _ = vti.parse_phpstan_json('{"files": {}, "errors": ["memory exhausted"]}')
    assert len(findings) == 1
    assert vti.classify_phpstan(findings), "an internal PHPStan error must disqualify"


def test_parse_phpstan_json_reports_unparseable_output():
    findings, err = vti.parse_phpstan_json("PHP Fatal error: boom")
    assert findings is None and "PHP Fatal error" in err


def test_missing_identifier_key_defaults_to_empty_not_crash():
    findings, _ = vti.parse_phpstan_json('{"files": {"a.php": {"messages": [{"line": 1}]}}}')
    assert findings[0]["identifier"] == ""
