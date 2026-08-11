"""Anti-leakage + provenance integrity guard for the WordPress critic evaluation corpus
(recommendation 09).

Ports the discipline of accessibility-skills' `test_blind_prompts.py` to the WordPress
critic corpus. The corpus is the set of fixtures carrying a `<id>.provenance.yaml` sidecar
(the pre-existing smoke/focused fixtures have no sidecar and are out of scope here — they
are governed by `validate-eval-suite-integrity.py`).

Why a sidecar and not dict-items in `domain_signals.must_detect` (as an earlier spec draft
proposed): `scripts/validate-eval-suite-integrity.py` freezes `domain_signals` values to
nonempty STRING lists and freezes metadata/rubric to a small set of exact-key profiles, and
whole-corpus tests assert every file matches one. Dict-items and a rich metadata block would
fail that validator and `llm_judge`. The grounding (cwe/sniff, file, line, severity),
tranche, provenance, license, expected_verdict, and tool-invisibility proof therefore live in
an un-policed `<id>.provenance.yaml` sidecar, and THIS test is what polices it.

The guard asserts, per corpus fixture:
  * the full quad (.md, .metadata.yaml, .rubric.yaml, .provenance.yaml) is present;
  * the sidecar schema (tranche/provenance/license/source/expected_verdict/status);
  * license is from the allowed set and no source is a non-commercial feed (WPScan/CC BY-NC);
  * tranche J proves tool-invisibility (phpcs + phpstan clean by construction);
  * tranche C is ACCEPT* with no `must_detect` (a finding raised there is a false positive);
  * NO answer-key content leaks into the review target `.md`
    (must_detect substrings, CWE-/sniff tokens, // BUG|VULN|FIXME hints, "this code has" preamble);
  * every grounding entry maps to a real must_detect item and carries cwe/sniff + severity;
  * status:draft fixtures are excluded from any scored run.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SUITES_ROOT = ROOT / "evals" / "suites"
HARNESS = ROOT / "evals" / "harness"

CRITIC_SUITES = (
    "wordpress-critic",
    "wordpress-security-critic",
    "wordpress-performance-critic",
    "wordpress-theme-critic",
)

TRANCHES = {"T", "J", "C"}
PROVENANCES = {"tool", "researcher", "authored"}
ALLOWED_LICENSES = {
    "GPL-2.0-or-later", "GPL-2.0-only", "GPL-3.0-or-later", "GPL-3.0-only", "MIT",
}
ACCEPT_VERDICTS = {"ACCEPT", "ACCEPT-WITH-RESERVATIONS"}
ALL_VERDICTS = ACCEPT_VERDICTS | {"REVISE", "REJECT"}
STATUSES = {"active", "draft"}
SIDECAR_REQUIRED = {
    "fixture_id", "tranche", "provenance", "license", "source", "expected_verdict", "status",
}
# Non-commercial / redistribution-restricted sources that must never seed a fixture.
FORBIDDEN_SOURCE_MARKERS = ("wpscan", "cc by-nc", "cc-by-nc", "noncommercial", "non-commercial")
# Answer-key hint patterns that must never appear in a review target.
HINT_TOKENS = (
    "// bug", "//bug", "# bug", "/* bug", "// vuln", "//vuln", "# vuln", "// fixme",
    "//fixme", "# fixme", "// todo: security", "@vuln", "cwe-", "wordpress.security.",
    "wordpress.db.", "wordpress.wp.", "vipcs.", "this code has", "the bug is",
    "the vulnerability", "insecure because", "is vulnerable",
)


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _corpus_sidecars() -> list[Path]:
    out: list[Path] = []
    for suite in CRITIC_SUITES:
        fixtures = SUITES_ROOT / suite / "fixtures"
        if fixtures.is_dir():
            out.extend(sorted(fixtures.glob("*.provenance.yaml")))
    return out


SIDECARS = _corpus_sidecars()
SIDECAR_IDS = [f"{p.parents[1].name}/{p.name[:-len('.provenance.yaml')]}" for p in SIDECARS]


def _fixture_id(sidecar: Path) -> str:
    return sidecar.name[: -len(".provenance.yaml")]


def test_corpus_is_nonempty():
    # This guard is meaningless if it silently policing nothing. The corpus must exist.
    assert SIDECARS, "no *.provenance.yaml sidecars found; the critic corpus is empty"


@pytest.mark.parametrize("sidecar", SIDECARS, ids=SIDECAR_IDS)
def test_quad_is_complete(sidecar: Path):
    fid = _fixture_id(sidecar)
    fixtures = sidecar.parent
    rubrics = fixtures.parent / "rubrics"
    assert (fixtures / f"{fid}.md").exists(), f"missing review target {fid}.md"
    assert (fixtures / f"{fid}.metadata.yaml").exists(), f"missing metadata for {fid}"
    assert (rubrics / f"{fid}.rubric.yaml").exists(), f"missing rubric for {fid}"


@pytest.mark.parametrize("sidecar", SIDECARS, ids=SIDECAR_IDS)
def test_sidecar_schema(sidecar: Path):
    fid = _fixture_id(sidecar)
    data = _load_yaml(sidecar)
    missing = SIDECAR_REQUIRED - set(data)
    assert not missing, f"{fid}: sidecar missing keys {sorted(missing)}"
    assert data["fixture_id"] == fid, f"{fid}: fixture_id mismatch ({data['fixture_id']})"
    assert data["tranche"] in TRANCHES, f"{fid}: tranche {data['tranche']!r} not in {TRANCHES}"
    assert data["provenance"] in PROVENANCES, f"{fid}: provenance {data['provenance']!r} invalid"
    assert data["license"] in ALLOWED_LICENSES, f"{fid}: license {data['license']!r} not allowed"
    assert data["expected_verdict"] in ALL_VERDICTS, f"{fid}: verdict {data['expected_verdict']!r} invalid"
    assert str(data["status"]).lower() in STATUSES, f"{fid}: status {data['status']!r} invalid"


@pytest.mark.parametrize("sidecar", SIDECARS, ids=SIDECAR_IDS)
def test_source_is_not_a_noncommercial_feed(sidecar: Path):
    fid = _fixture_id(sidecar)
    source = str(_load_yaml(sidecar).get("source", "")).lower()
    hit = [m for m in FORBIDDEN_SOURCE_MARKERS if m in source]
    assert not hit, f"{fid}: source references a non-commercial feed {hit} (WPScan/CC BY-NC forbidden)"


@pytest.mark.parametrize("sidecar", SIDECARS, ids=SIDECAR_IDS)
def test_tranche_J_proves_tool_invisibility(sidecar: Path):
    fid = _fixture_id(sidecar)
    data = _load_yaml(sidecar)
    if data.get("tranche") != "J":
        pytest.skip("not tranche J")
    ti = data.get("tool_invisibility")
    assert isinstance(ti, dict), f"{fid}: tranche J requires a tool_invisibility block"
    for key in ("phpcs_wordpress", "phpstan", "plugin_check", "verified_on"):
        assert key in ti, f"{fid}: tool_invisibility missing {key}"
    # The entry criterion: static tools do NOT fire. phpcs + phpstan must be clean; a J
    # fixture a linter catches is mislabeled and belongs in tranche T.
    for key in ("phpcs_wordpress", "phpstan"):
        assert str(ti[key]).lower() == "clean", (
            f"{fid}: tranche J requires {key}=clean (found {ti[key]!r}); "
            "a tool-caught defect belongs in tranche T")
    assert str(ti["plugin_check"]).lower() in {"clean", "pending"}, (
        f"{fid}: plugin_check must be clean or pending, got {ti['plugin_check']!r}")


@pytest.mark.parametrize("sidecar", SIDECARS, ids=SIDECAR_IDS)
def test_tranche_C_is_accept_with_no_must_detect(sidecar: Path):
    fid = _fixture_id(sidecar)
    data = _load_yaml(sidecar)
    if data.get("tranche") != "C":
        pytest.skip("not tranche C")
    assert data["expected_verdict"] in ACCEPT_VERDICTS, (
        f"{fid}: tranche C must be ACCEPT*, got {data['expected_verdict']!r}")
    rubric = _load_yaml(sidecar.parent.parent / "rubrics" / f"{fid}.rubric.yaml")
    md = (rubric.get("domain_signals") or {}).get("must_detect")
    assert not md, f"{fid}: tranche C rubric must have no must_detect (a finding there is a false positive)"
    # It must still bait: must_not_penalize_or_do names what a weak critic would wrongly flag.
    anti = (rubric.get("domain_signals") or {}).get("must_not_penalize_or_do")
    assert anti, f"{fid}: tranche C rubric must carry must_not_penalize_or_do (the bait)"


@pytest.mark.parametrize("sidecar", SIDECARS, ids=SIDECAR_IDS)
def test_no_answer_key_leaks_into_review_target(sidecar: Path):
    fid = _fixture_id(sidecar)
    md_text = (sidecar.parent / f"{fid}.md").read_text(encoding="utf-8").lower()
    for token in HINT_TOKENS:
        assert token not in md_text, f"{fid}.md leaks a hint token: {token!r}"
    rubric = _load_yaml(sidecar.parent.parent / "rubrics" / f"{fid}.rubric.yaml")
    signals = rubric.get("domain_signals") or {}
    for desc in signals.get("must_detect", []) or []:
        assert desc.lower() not in md_text, (
            f"{fid}.md leaks the must_detect description verbatim: {desc!r}")
    for anti in signals.get("must_not_penalize_or_do", []) or []:
        assert anti.lower() not in md_text, (
            f"{fid}.md leaks the must_not_penalize description verbatim: {anti!r}")


@pytest.mark.parametrize("sidecar", SIDECARS, ids=SIDECAR_IDS)
def test_grounding_maps_to_real_must_detect_items(sidecar: Path):
    fid = _fixture_id(sidecar)
    data = _load_yaml(sidecar)
    grounding = data.get("grounding") or []
    if data.get("tranche") == "C":
        assert not grounding, f"{fid}: tranche C has nothing to ground"
        return
    rubric = _load_yaml(sidecar.parent.parent / "rubrics" / f"{fid}.rubric.yaml")
    must_detect = set((rubric.get("domain_signals") or {}).get("must_detect", []) or [])
    for entry in grounding:
        assert isinstance(entry, dict), f"{fid}: grounding entries must be mappings"
        assert entry.get("description") in must_detect, (
            f"{fid}: grounding description not in must_detect: {entry.get('description')!r}")
        assert str(entry.get("severity", "")).upper() in {"MINOR", "MAJOR", "CRITICAL"}, (
            f"{fid}: grounding severity invalid: {entry.get('severity')!r}")
        assert entry.get("cwe") or entry.get("sniff"), (
            f"{fid}: grounding entry needs a cwe or sniff: {entry}")


@pytest.mark.parametrize("sidecar", SIDECARS, ids=SIDECAR_IDS)
def test_no_active_fixture_is_a_draft_in_the_scored_root(sidecar: Path):
    # Draft CVE stubs must live under fixtures/_drafts/ (non-globbed), never directly in
    # fixtures/, so they cannot enter a scored run. A sidecar found here by the glob is in
    # the scored root, so it must not be a draft.
    data = _load_yaml(sidecar)
    assert str(data.get("status", "active")).lower() != "draft", (
        f"{_fixture_id(sidecar)}: a status:draft fixture is in the scored fixtures/ root; "
        "stage drafts under fixtures/_drafts/ until the human gate promotes them")


def test_scorer_excludes_draft_fixtures(tmp_path):
    """A status:draft sidecar must never enter a scored run."""
    import sys
    sys.path.insert(0, str(HARNESS))
    try:
        import answer_key_score as ak
    finally:
        sys.path.remove(str(HARNESS))
    suite = tmp_path / "suite"
    (suite / "fixtures").mkdir(parents=True)
    (suite / "fixtures" / "active-one.md").write_text("x", encoding="utf-8")
    (suite / "fixtures" / "active-one.provenance.yaml").write_text(
        "fixture_id: active-one\nstatus: active\ntranche: J\n", encoding="utf-8")
    (suite / "fixtures" / "draft-one.md").write_text("x", encoding="utf-8")
    (suite / "fixtures" / "draft-one.provenance.yaml").write_text(
        "fixture_id: draft-one\nstatus: draft\ntranche: J\n", encoding="utf-8")
    (suite / "fixtures" / "no-sidecar.md").write_text("x", encoding="utf-8")  # legacy smoke
    assert ak.discover_corpus_fixtures(suite) == ["active-one"]
