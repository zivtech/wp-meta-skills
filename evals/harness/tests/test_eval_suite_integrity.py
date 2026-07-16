"""Strict schema and parser contracts for eval-suite YAML documents."""
from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "validate-eval-suite-integrity.py"
SPEC = importlib.util.spec_from_file_location("eval_suite_integrity", SCRIPT)
assert SPEC and SPEC.loader
integrity = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = integrity
SPEC.loader.exec_module(integrity)


def _eval_config(suite: str = "sample-suite") -> dict:
    return {
        "skill": {"name": suite, "type": "critic", "status": "experimental"},
        "fixtures": {
            "directory": "./fixtures",
            "count": 1,
            "pattern": "*.md",
            "metadata_suffix": ".metadata.yaml",
        },
        "rubrics": {"directory": "./rubrics", "scoring_method": "quality_weighted"},
        "baselines": {
            "directory": "./baselines",
            "conditions": ["baseline-zero-shot", "baseline-few-shot"],
        },
        "evaluation": {"status": "smoke", "full_run_status": "blocked"},
        "invocation": {
            "model": "sonnet",
            "effort": "low",
            "baseline_provider": "codex",
            "baseline_model_policy": "newest-at-run-time",
            "baseline_model": "gpt-test",
            "baseline_effort": "medium",
            "note": "Synthetic hermetic test config.",
        },
        "output_contract_oracle": {
            "type": "deterministic",
            "command": "python oracle.py",
            "status": "available",
        },
    }


def _metadata(suite: str = "sample-suite", fixture: str = "case") -> dict:
    return {
        "name": fixture,
        "suite": suite,
        "skill_under_test": suite,
        "skill_type": "critic",
        "difficulty_tier": "smoke",
        "provenance": "synthetic",
        "expected_behavior": ["Names an exact verification surface"],
    }


def _rubric(suite: str = "sample-suite", fixture: str = "case") -> dict:
    return {
        "fixture": fixture,
        "skill_under_test": suite,
        "max_score": 2,
        "criteria": [
            {"id": "quality", "weight": 2, "description": "Find the material issue."}
        ],
    }


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _suite(tmp_path: Path, suite: str = "sample-suite") -> Path:
    suite_dir = tmp_path / suite
    _write_yaml(suite_dir / "eval.yaml", _eval_config(suite))
    (suite_dir / "fixtures").mkdir(parents=True)
    (suite_dir / "fixtures" / "case.md").write_text("Fixture\n", encoding="utf-8")
    _write_yaml(suite_dir / "fixtures" / "case.metadata.yaml", _metadata(suite))
    _write_yaml(suite_dir / "rubrics" / "case.rubric.yaml", _rubric(suite))
    return suite_dir


def _codes(suite_dir: Path) -> set[str]:
    return {issue.kind for issue in integrity.check_suite(suite_dir)}


def _document_path(suite_dir: Path, kind: str) -> Path:
    return {
        "eval": suite_dir / "eval.yaml",
        "metadata": suite_dir / "fixtures" / "case.metadata.yaml",
        "rubric": suite_dir / "rubrics" / "case.rubric.yaml",
    }[kind]


@pytest.mark.parametrize("kind", ("eval", "metadata", "rubric"))
def test_invalid_yaml_is_reported_once_without_schema_cascade(tmp_path, kind):
    suite_dir = _suite(tmp_path)
    _document_path(suite_dir, kind).write_text("root: [unterminated\n", encoding="utf-8")
    issues = integrity.check_suite(suite_dir)
    matching = [issue for issue in issues if issue.path == _document_path(suite_dir, kind)]
    assert [issue.kind for issue in matching] == [f"invalid_{kind}_yaml"]


@pytest.mark.parametrize("kind", ("eval", "metadata", "rubric"))
def test_duplicate_top_level_keys_are_rejected(tmp_path, kind):
    suite_dir = _suite(tmp_path)
    path = _document_path(suite_dir, kind)
    path.write_text("name: first\nname: second\n", encoding="utf-8")
    issues = integrity.check_suite(suite_dir)
    assert f"duplicate_{kind}_key" in {issue.kind for issue in issues}


def test_duplicate_nested_criterion_key_is_rejected_with_location(tmp_path):
    suite_dir = _suite(tmp_path)
    path = _document_path(suite_dir, "rubric")
    path.write_text(
        "fixture: case\nskill_under_test: sample-suite\nmax_score: 1\n"
        "criteria:\n  - id: one\n    id: two\n    weight: 1\n    description: x\n",
        encoding="utf-8",
    )
    issue = next(item for item in integrity.check_suite(suite_dir) if item.kind == "duplicate_rubric_key")
    assert "line" in issue.message and "column" in issue.message
    assert "two" not in issue.message


@pytest.mark.parametrize(
    ("payload", "kind"),
    (
        ("base: &base\n  value: one\ncopy: *base\n", "metadata"),
        ("name: !!str case\n", "metadata"),
        ("name: !private case\n", "metadata"),
    ),
)
def test_yaml_references_and_explicit_tags_are_rejected(tmp_path, payload, kind):
    suite_dir = _suite(tmp_path)
    _document_path(suite_dir, kind).write_text(payload, encoding="utf-8")
    assert f"invalid_{kind}_yaml" in _codes(suite_dir)


def test_oversized_document_is_rejected_without_parsing(tmp_path):
    suite_dir = _suite(tmp_path)
    path = _document_path(suite_dir, "metadata")
    path.write_bytes(b"name: case\npadding: " + b"x" * integrity.MAX_YAML_BYTES)
    assert "invalid_metadata_yaml" in _codes(suite_dir)


def test_deeply_nested_document_returns_an_issue_instead_of_recursing(tmp_path):
    suite_dir = _suite(tmp_path)
    path = _document_path(suite_dir, "metadata")
    path.write_text("value: " + "[" * 2_000 + "0" + "]" * 2_000, encoding="utf-8")
    assert "invalid_metadata_yaml" in _codes(suite_dir)


def test_escaped_surrogate_is_a_schema_issue_not_an_uncaught_error(tmp_path):
    suite_dir = _suite(tmp_path)
    path = _document_path(suite_dir, "metadata")
    payload = path.read_text(encoding="utf-8").replace("name: case", 'name: "\\uD800"')
    path.write_text(payload, encoding="utf-8")
    assert "schema_metadata_name" in _codes(suite_dir)


def test_escaped_surrogate_in_eval_and_rubric_is_fail_closed(tmp_path):
    suite_dir = _suite(tmp_path)
    eval_path = _document_path(suite_dir, "eval")
    payload = eval_path.read_text(encoding="utf-8").replace("model: sonnet", 'model: "\\uD800"')
    eval_path.write_text(payload, encoding="utf-8")
    assert "schema_eval_value" in _codes(suite_dir)
    suite_dir = _suite(tmp_path, "second-suite")
    rubric_path = _document_path(suite_dir, "rubric")
    payload = rubric_path.read_text(encoding="utf-8").replace(
        "description: Find the material issue.", 'description: "\\uD800"'
    )
    rubric_path.write_text(payload, encoding="utf-8")
    assert "schema_rubric_criterion_description" in _codes(suite_dir)


@pytest.mark.parametrize("kind", ("eval", "metadata", "rubric"))
@pytest.mark.parametrize("root", ([], "scalar"))
def test_non_mapping_roots_fail_schema(tmp_path, kind, root):
    suite_dir = _suite(tmp_path)
    _write_yaml(_document_path(suite_dir, kind), root)
    assert f"schema_{kind}_root" in _codes(suite_dir)


def _mutate_eval(suite_dir: Path, mutation) -> None:
    path = suite_dir / "eval.yaml"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutation(value)
    _write_yaml(path, value)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.__setitem__("fixtures", []),
        lambda value: value.__setitem__("rubrics", "rubrics"),
        lambda value: value["fixtures"].__setitem__("directory", []),
        lambda value: value["fixtures"].__setitem__("directory", "/tmp/escape"),
        lambda value: value["fixtures"].__setitem__("directory", "../escape"),
        lambda value: value["fixtures"].__setitem__("pattern", []),
        lambda value: value["fixtures"].__setitem__("pattern", "../*.md"),
        lambda value: value["fixtures"].__setitem__("metadata_suffix", 1),
        lambda value: value["fixtures"].__setitem__("metadata_suffix", "../meta.yaml"),
        lambda value: value["fixtures"].__setitem__("count", -1),
        lambda value: value["fixtures"].__setitem__("count", True),
        lambda value: value.__setitem__("evaluation", []),
        lambda value: value["invocation"].__setitem__("model", ["sonnet"]),
        lambda value: value["invocation"].__setitem__("model", {"nested": "sonnet"}),
        lambda value: value["output_contract_oracle"].__setitem__("command", {"nested": "command"}),
        lambda value: value["skill"].__setitem__("status", {"nested": "status"}),
        lambda value: value["evaluation"].__setitem__("status", {"nested": "status"}),
        lambda value: value["baselines"].__setitem__("conditions", "baseline"),
        lambda value: value["skill"].__setitem__("unknown", "not-profiled"),
    ),
)
def test_malformed_eval_values_stop_before_globbing(tmp_path, mutation):
    suite_dir = _suite(tmp_path)
    _mutate_eval(suite_dir, mutation)
    issues = integrity.check_suite(suite_dir)
    assert any(issue.kind.startswith("schema_eval_") for issue in issues)
    assert not any(issue.kind in {"missing_metadata", "missing_rubric"} for issue in issues)


def test_recursive_fixture_glob_is_rejected_before_inventory(tmp_path, monkeypatch):
    suite_dir = _suite(tmp_path)
    nested = suite_dir / "fixtures" / "nested"
    nested.mkdir()
    (nested / "hidden.md").write_text("Hidden\n", encoding="utf-8")
    _mutate_eval(suite_dir, lambda value: value["fixtures"].__setitem__("pattern", "**"))
    monkeypatch.setattr(integrity, "_regular_paths", lambda *_: pytest.fail("inventory reached"))
    assert "schema_eval_fixtures" in _codes(suite_dir)


def test_eval_named_profiles_cover_positive_examples_and_live_corpus():
    expected = {"standard", "executor-full", "executor-static", "candidate-comparison"}
    observed = set()
    for path in sorted((ROOT / "evals" / "suites").glob("*/eval.yaml")):
        document, issues = integrity.read_yaml_document(path, path.parent.name, "eval")
        assert not issues and document is not None
        matches = integrity.match_eval_profiles(document)
        assert len(matches) == 1, path
        observed.update(matches)
    assert observed == expected


def _mutate_metadata(suite_dir: Path, mutation) -> None:
    path = _document_path(suite_dir, "metadata")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutation(value)
    _write_yaml(path, value)


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        (lambda value: value.__setitem__("name", "other"), "schema_metadata_name"),
        (lambda value: value.pop("name"), "schema_metadata_name"),
        (lambda value: value.__setitem__("name", " "), "schema_metadata_name"),
        (lambda value: value.__setitem__("skill_under_test", []), "schema_metadata_scalar"),
        (lambda value: value.__setitem__("suite", "other-suite"), "schema_metadata_identity"),
        (lambda value: value.__setitem__("expected_behavior", []), "schema_metadata_expectations"),
        (lambda value: value.__setitem__("expected_behavior", ["ok", " "]), "schema_metadata_expectations"),
        (lambda value: value.__setitem__("expected_behavior", ["ok", 2]), "schema_metadata_expectations"),
        (lambda value: value.update({"skill": "ambiguous"}), "schema_metadata_profile"),
    ),
)
def test_metadata_identity_and_expectation_contracts(tmp_path, mutation, code):
    suite_dir = _suite(tmp_path)
    _mutate_metadata(suite_dir, mutation)
    assert code in _codes(suite_dir)


@pytest.mark.parametrize(
    "runtime_assertions",
    (
        {"block_name": "acme/card", "frontend_selector": ".wp-block-acme-card"},
        {
            "block_name": "acme/card",
            "frontend_selector": ".wp-block-acme-other",
            "expected_frontend_text": "Visible text",
        },
        {
            "block_name": "acme/card",
            "frontend_selector": ".wp-block-acme-card",
            "expected_frontend_text": "<b>HTML</b>",
        },
        {
            "block_name": "acme/card",
            "frontend_selector": ".wp-block-acme-card",
            "expected_frontend_text": "Visible text",
            "unknown": "not allowed",
        },
    ),
)
def test_metadata_runtime_assertions_reuse_exact_plan011_contract(tmp_path, runtime_assertions):
    suite_dir = _suite(tmp_path)
    _mutate_metadata(suite_dir, lambda value: value.__setitem__("runtime_assertions", runtime_assertions))
    assert "schema_metadata_runtime_assertions" in _codes(suite_dir)


def test_valid_runtime_assertions_and_all_metadata_profiles_map_once(tmp_path):
    suite_dir = _suite(tmp_path)
    assertions = {
        "block_name": "acme/card",
        "frontend_selector": ".wp-block-acme-card",
        "expected_frontend_text": "Visible text",
    }
    _mutate_metadata(suite_dir, lambda value: value.__setitem__("runtime_assertions", assertions))
    assert not _codes(suite_dir)
    expected = {"legacy-skill", "suite-smoke", "suite-risk", "candidate-comparison"}
    observed = set()
    for path in sorted((ROOT / "evals" / "suites").glob("*/fixtures/*.metadata.yaml")):
        document, issues = integrity.read_yaml_document(path, path.parents[1].name, "metadata")
        assert not issues and document is not None
        matches = integrity.match_metadata_profiles(document)
        assert len(matches) == 1, path
        observed.update(matches)
    assert observed == expected


def _mutate_rubric(suite_dir: Path, mutation) -> None:
    path = _document_path(suite_dir, "rubric")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutation(value)
    _write_yaml(path, value)


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        (lambda value: value.__setitem__("fixture", "other"), "schema_rubric_fixture"),
        (lambda value: value.__setitem__("fixture", " "), "schema_rubric_fixture"),
        (lambda value: value.pop("max_score"), "schema_rubric_score"),
        (lambda value: value.__setitem__("max_score", 0), "schema_rubric_score"),
        (lambda value: value.__setitem__("max_score", True), "schema_rubric_score"),
        (lambda value: value.__setitem__("max_score", "2"), "schema_rubric_score"),
        (lambda value: value.__setitem__("max_score", 10 ** 1_000), "schema_rubric_score"),
        (lambda value: value.__setitem__("criteria", []), "schema_rubric_criteria"),
        (lambda value: value["criteria"][0].__setitem__("id", " "), "schema_rubric_criterion_id"),
        (lambda value: value["criteria"].append(deepcopy(value["criteria"][0])), "schema_rubric_criterion_id"),
        (lambda value: value["criteria"][0].__setitem__("weight", 0), "schema_rubric_criterion_weight"),
        (lambda value: value["criteria"][0].__setitem__("weight", True), "schema_rubric_criterion_weight"),
        (lambda value: value["criteria"][0].__setitem__("description", " "), "schema_rubric_criterion_description"),
        (lambda value: value["criteria"][0].__setitem__("type", []), "schema_rubric_criterion_category"),
        (lambda value: value["criteria"][0].__setitem__("type", "unknown"), "schema_rubric_criterion_category"),
        (
            lambda value: value["criteria"][0].update({"type": "quality", "category": "false_positive_trap"}),
            "schema_rubric_criterion_category",
        ),
        (lambda value: value.__setitem__("max_score", 3), "schema_rubric_weight_sum"),
    ),
)
def test_rubric_identity_score_and_criterion_contracts(tmp_path, mutation, code):
    suite_dir = _suite(tmp_path)
    _mutate_rubric(suite_dir, mutation)
    assert code in _codes(suite_dir)


@pytest.mark.parametrize(
    "domain_signals",
    (
        [],
        {"unknown": ["value"]},
        {"must_detect": "value"},
        {"must_detect": []},
        {"must_detect": ["ok", " "]},
    ),
)
def test_malformed_domain_signals_fail(tmp_path, domain_signals):
    suite_dir = _suite(tmp_path)
    _mutate_rubric(suite_dir, lambda value: value.__setitem__("domain_signals", domain_signals))
    assert "schema_rubric_domain_signals" in _codes(suite_dir)


@pytest.mark.parametrize(
    "gate",
    (
        [],
        {"required_delta": 0.2},
        {"required_delta": True, "fallback": "pairwise"},
        {"required_delta": 0.2, "fallback": " ", "unknown": "x"},
    ),
)
def test_malformed_discrimination_gate_fails(tmp_path, gate):
    suite_dir = _suite(tmp_path)
    def mutation(value):
        value.pop("skill_under_test")
        value["scoring_method"] = "quality_weighted"
        value["domain_signals"] = {"must_detect": ["Exact risk"]}
        value["discrimination_gate"] = gate
    _mutate_rubric(suite_dir, mutation)
    assert "schema_rubric_discrimination_gate" in _codes(suite_dir)


def test_weight_sum_uses_documented_tolerance(tmp_path):
    suite_dir = _suite(tmp_path)
    def mutation(value):
        value["max_score"] = 0.3
        value["criteria"] = [
            {"id": "one", "weight": 0.1, "description": "One"},
            {"id": "two", "weight": 0.2, "description": "Two"},
        ]
    _mutate_rubric(suite_dir, mutation)
    assert "schema_rubric_weight_sum" not in _codes(suite_dir)


def test_finite_weights_with_overflowing_sum_fail_closed(tmp_path):
    suite_dir = _suite(tmp_path)
    def mutation(value):
        value["max_score"] = 1e308
        value["criteria"] = [
            {"id": "one", "weight": 1e308, "description": "One"},
            {"id": "two", "weight": 1e308, "description": "Two"},
        ]
    _mutate_rubric(suite_dir, mutation)
    assert "schema_rubric_weight_sum" in _codes(suite_dir)


def test_false_positive_trap_category_is_inverted_by_real_scorer():
    harness = ROOT / "evals" / "harness"
    sys.path.insert(0, str(harness))
    try:
        import llm_judge
        base = {"id": "criterion", "weight": 1, "description": "Criterion"}
        positive = llm_judge._extract_criteria_from_rubric({"criteria": [base]})
        trap = llm_judge._extract_criteria_from_rubric(
            {"criteria": [base | {"type": "false_positive_trap"}]}
        )
        positive_result = llm_judge.JudgeResult("case", "test", [
            llm_judge.CriterionResult("criterion", positive[0]["category"], "Criterion", True, 1, "", 1)
        ])
        trap_result = llm_judge.JudgeResult("case", "test", [
            llm_judge.CriterionResult("criterion", trap[0]["category"], "Criterion", True, 1, "", 1)
        ])
        avoided_trap_result = llm_judge.JudgeResult("case", "test", [
            llm_judge.CriterionResult("criterion", trap[0]["category"], "Criterion", False, 1, "", 1)
        ])
        llm_judge._compute_scores(positive_result, {"criteria": [base]})
        llm_judge._compute_scores(trap_result, {"criteria": [base | {"type": "false_positive_trap"}]})
        llm_judge._compute_scores(avoided_trap_result, {"criteria": [base | {"type": "false_positive_trap"}]})
        assert positive_result.composite_score == 100
        assert trap_result.composite_score == 0
        assert avoided_trap_result.composite_score == 100
    finally:
        sys.path.remove(str(harness))


def _score_extracted(llm_judge, rubric, extracted, positive_met, trap_met):
    results = [
        llm_judge.CriterionResult(
            item["criterion_id"], item["category"], item["description"],
            trap_met if item["category"] == "false_positive_trap" else positive_met,
            1, "", item.get("weight", 1.0),
        )
        for item in extracted
    ]
    result = llm_judge.JudgeResult("case", "test", results)
    llm_judge._compute_scores(result, rubric)
    return result.composite_score


def test_all_domain_signal_keys_have_unique_real_scorer_semantics():
    harness = ROOT / "evals" / "harness"
    sys.path.insert(0, str(harness))
    try:
        import llm_judge
        rubric = {
            "criteria": [{"id": "base", "weight": 2, "description": "Base"}],
            "domain_signals": {
                "expected_wordpress_apis": ["current_user_can"],
                "expected_surfaces": ["blueprint.json"],
                "must_detect": ["missing authorization"],
                "must_not_claim": ["runtime proof exists"],
                "must_not_penalize_or_do": ["reject a safe public read"],
            },
        }
        extracted = llm_judge._extract_criteria_from_rubric(rubric)
        assert integrity.DOMAIN_SIGNAL_KEYS == llm_judge.DOMAIN_SIGNAL_KEYS
        assert [item["criterion_id"] for item in extracted] == [
            "base", "domain_expected_wordpress_apis", "domain_expected_surfaces",
            "domain_must_detect_1", "domain_false_positive_trap_1",
            "domain_must_not_claim_trap_1",
        ]
        assert [item["category"] for item in extracted] == [
            "quality", "domain_wordpress_api", "quality", "domain_must_detect",
            "false_positive_trap", "false_positive_trap",
        ]
        assert [item.get("weight", 1.0) for item in extracted] == [2, 1, 1, 1, 1, 1]
        assert len({item["criterion_id"] for item in extracted}) == 6
        assert _score_extracted(llm_judge, rubric, extracted, True, True) == 71.43
        assert _score_extracted(llm_judge, rubric, extracted, False, True) == 0
        assert _score_extracted(llm_judge, rubric, extracted, True, False) == 100
    finally:
        sys.path.remove(str(harness))


@pytest.mark.parametrize("key", tuple(sorted(integrity.DOMAIN_SIGNAL_KEYS)))
def test_real_scorer_rejects_scalar_domain_signals(key):
    harness = ROOT / "evals" / "harness"
    sys.path.insert(0, str(harness))
    try:
        import llm_judge
        with pytest.raises(ValueError, match="nonempty string list"):
            llm_judge._extract_criteria_from_rubric({"domain_signals": {key: "unsafe"}})
    finally:
        sys.path.remove(str(harness))


def test_real_scorer_rejects_blank_and_unknown_domain_signals():
    harness = ROOT / "evals" / "harness"
    sys.path.insert(0, str(harness))
    try:
        import llm_judge
        with pytest.raises(ValueError, match="nonblank strings"):
            llm_judge._extract_criteria_from_rubric(
                {"domain_signals": {"expected_surfaces": [" "]}}
            )
        with pytest.raises(ValueError, match="accepted fields"):
            llm_judge._extract_criteria_from_rubric(
                {"domain_signals": {"unknown": ["value"]}}
            )
        with pytest.raises(ValueError, match="duplicate criterion IDs"):
            llm_judge._extract_criteria_from_rubric({
                "criteria": [{
                    "id": "domain_expected_surfaces", "weight": 1,
                    "description": "Collision",
                }],
                "domain_signals": {"expected_surfaces": ["blueprint.json"]},
            })
    finally:
        sys.path.remove(str(harness))


def test_all_rubric_profiles_map_once_and_live_corpus_validates():
    expected = {"weighted", "weighted-domain", "candidate-comparison"}
    observed = set()
    for path in sorted((ROOT / "evals" / "suites").glob("*/rubrics/*.rubric.yaml")):
        document, issues = integrity.read_yaml_document(path, path.parents[1].name, "rubric")
        assert not issues and document is not None
        matches = integrity.match_rubric_profiles(document)
        assert len(matches) == 1, path
        observed.update(matches)
    assert observed == expected
    strict = {
        "wordpress-plugin-executor", "wordpress-block-executor",
        "wordpress-security-critic", "wordpress-performance-critic",
        "wordpress-planner.migration", "wordpress-blueprint-executor",
        "wordpress-skill-candidate-eval",
    }
    for suite in strict:
        assert not integrity.check_suite(ROOT / "evals" / "suites" / suite)


def test_structural_issues_cannot_be_quarantined_for_two_files(tmp_path):
    suite_dir = _suite(tmp_path)
    metadata = suite_dir / "fixtures" / "second.metadata.yaml"
    metadata.write_text("name: one\nname: two\n", encoding="utf-8")
    rubric = suite_dir / "rubrics" / "case.rubric.yaml"
    rubric.write_text("fixture: [unterminated\n", encoding="utf-8")
    issues = integrity.check_suite(suite_dir)
    structural = [item for item in issues if item.kind.startswith(("invalid_", "duplicate_", "schema_"))]
    known = {(suite_dir.name, item.kind) for item in structural}
    assert len(structural) == 2
    assert all(not integrity.is_known(item, known) for item in structural)


def test_missing_requested_strict_suite_is_an_unsuppressible_error(tmp_path):
    issues = integrity.collect_integrity_issues({"missing-suite"}, tmp_path)
    assert [(issue.suite, issue.kind) for issue in issues] == [
        ("missing-suite", "schema_strict_suite")
    ]
    assert not integrity.is_known(issues[0], {("missing-suite", "schema_strict_suite")})


def test_suite_root_symlink_is_rejected_without_following(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside-suite"
    _suite(outside, "linked-suite")
    (tmp_path / "linked-suite").symlink_to(outside / "linked-suite", target_is_directory=True)
    issues = integrity.collect_integrity_issues({"linked-suite"}, tmp_path)
    assert [(issue.suite, issue.kind) for issue in issues] == [
        ("linked-suite", "schema_suite_root")
    ]


def test_diagnostic_output_escapes_control_characters(tmp_path):
    issue = integrity.Issue(
        "suite\n::error title=forged::message", "schema_eval_value",
        tmp_path / "bad\npath", "field\n::error title=forged::message\x1b[31m",
    )
    rendered = integrity.format_issue(issue, "ERROR")
    assert "\n" not in rendered and "\x1b" not in rendered
    assert "\\n::error" in rendered and "\\x1b" in rendered


def test_quality_gap_ledger_is_bounded_and_does_not_follow_symlinks(tmp_path):
    valid = tmp_path / "valid.md"
    valid.write_text("- suite=sample scope=placeholder status=quarantined\n", encoding="utf-8")
    known, issues = integrity.parse_quality_gaps(valid)
    assert known == {("sample", "placeholder")} and not issues
    linked = tmp_path / "linked.md"
    linked.symlink_to(valid)
    known, issues = integrity.parse_quality_gaps(linked)
    assert not known and [issue.kind for issue in issues] == ["schema_quality_gaps"]
    oversized = tmp_path / "oversized.md"
    oversized.write_bytes(b"x" * (integrity.MAX_YAML_BYTES + 1))
    known, issues = integrity.parse_quality_gaps(oversized)
    assert not known and [issue.kind for issue in issues] == ["schema_quality_gaps"]


def test_malformed_quality_gap_ledger_fails_the_strict_main_gate(tmp_path, monkeypatch):
    ledger = tmp_path / "QUALITY_GAPS.md"
    ledger.write_bytes(b"x" * (integrity.MAX_YAML_BYTES + 1))
    monkeypatch.setattr(integrity, "QUALITY_GAPS", ledger)
    monkeypatch.setattr(integrity, "SUITES_ROOT", tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["validate-eval-suite-integrity.py", "--strict-suites", "sample", "--allow-known-gaps"]
    )
    assert integrity.main() == 1
