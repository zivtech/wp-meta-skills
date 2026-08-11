"""Unit tests for the CVE-diff pipeline's PURE logic (localization + draft emission).

The fetch step (svn/network) is I/O and not tested here; the diff localization and the
draft-quad emission — the parts that decide WHERE the defect is and WHAT gets written —
are pure and covered.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_cve_fixtures as bcf


VULNERABLE = """<?php
function acme_delete() {
    $id = intval($_POST['id']);
    wp_delete_post($id);
}
"""

PATCHED = """<?php
function acme_delete() {
    if (!current_user_can('delete_posts')) {
        wp_die('forbidden');
    }
    $id = intval($_POST['id']);
    wp_delete_post($id);
}
"""


def test_localize_defect_finds_the_missing_guard_region():
    hunks = bcf.localize_defect(VULNERABLE, PATCHED)
    # The patch INSERTS a capability guard; on the vulnerable side that shows up as a
    # 'replace'/'delete' boundary around where the guard was missing (line 3, the body start).
    assert hunks, "expected at least one localized hunk"
    assert all(h.start <= h.end for h in hunks)
    assert all(h.start >= 1 for h in hunks)


def test_localize_defect_identical_source_is_empty():
    assert bcf.localize_defect(VULNERABLE, VULNERABLE) == []


def test_emit_draft_fixture_stages_under_drafts_and_marks_draft():
    seed = bcf.Seed(slug="acme", cve="CVE-2024-0001", vulnerable_version="1.0",
                    patched_version="1.1", cwe="CWE-862", suite="wordpress-security-critic")
    files = bcf.emit_draft_fixture(seed, VULNERABLE, PATCHED, "acme.php")
    paths = set(files)
    assert any(p.endswith("/_drafts/acme-cve-2024-0001.md") for p in paths)
    assert any(p.endswith("/_drafts/acme-cve-2024-0001-clean.md") for p in paths)
    sidecar = next(v for k, v in files.items() if k.endswith(".provenance.yaml"))
    # A draft is out of every scored run and every globbed gate.
    assert "status: draft" in sidecar
    assert "provenance: researcher" in sidecar
    assert "cve:CVE-2024-0001" in sidecar
    assert "CWE-862" in sidecar
    assert "HUMAN GATE" in sidecar
    # every staged path lives under the non-globbed _drafts/ dir
    assert all("/fixtures/_drafts/" in p for p in paths)


def test_draft_review_target_is_blind():
    md = bcf.draft_review_target("acme", "CVE-2024-0001", VULNERABLE)
    low = md.lower()
    for token in ("// bug", "// vuln", "cwe-", "the vulnerability", "is vulnerable"):
        assert token not in low, f"draft review target leaked hint token {token!r}"
    assert "```php" in md


def test_seed_from_dict_defaults_suite():
    s = bcf.Seed.from_dict({"slug": "x", "cve": "CVE-0", "vulnerable_version": "1",
                            "patched_version": "2"})
    assert s.suite == "wordpress-security-critic" and s.cwe == "CWE-unknown"
