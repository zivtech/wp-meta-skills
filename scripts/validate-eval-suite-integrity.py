#!/usr/bin/env python3
"""Validate eval-suite YAML, schema, pairing, and placeholder integrity."""

from __future__ import annotations

import argparse
import math
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver
from yaml.tokens import AliasToken, AnchorToken, TagToken


ROOT = Path(__file__).resolve().parent.parent
SUITES_ROOT = ROOT / "evals" / "suites"
QUALITY_GAPS = SUITES_ROOT / "QUALITY_GAPS.md"
HARNESS_ROOT = ROOT / "evals" / "harness"
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))
from runtime_assertions import make_block_runtime_assertion  # noqa: E402


MAX_YAML_BYTES = 1_048_576
WEIGHT_TOLERANCE = 1e-6
STRUCTURAL_PREFIXES = ("invalid_", "duplicate_", "schema_")
PLACEHOLDER_MARKERS = (
    "TBD",
    "Placeholder",
    "[Finding",
    "[False positive test]",
    "Full metadata needs to be written",
)


def _fields(value: str) -> frozenset[str]:
    return frozenset(value.split())


EVAL_PROFILE_KEYS = {
    "standard": _fields("skill fixtures rubrics baselines evaluation invocation output_contract_oracle"),
    "executor-full": _fields("skill fixtures rubrics baselines evaluation invocation output_contract_oracle oracle materializer certifier artifact_oracle"),
    "executor-static": _fields("skill fixtures rubrics baselines evaluation invocation output_contract_oracle artifact_oracle"),
    "candidate-comparison": _fields("skill fixtures rubrics context_documents baselines invocation candidate_lanes statistical_design alternate_measurement_targets"),
}
EVAL_MAPPING_SECTIONS = frozenset({
    "skill", "fixtures", "rubrics", "baselines", "evaluation", "invocation",
    "output_contract_oracle", "oracle", "materializer", "certifier",
    "artifact_oracle", "statistical_design", "alternate_measurement_targets",
})
EVAL_LIST_SECTIONS = frozenset({"context_documents", "candidate_lanes"})
EVAL_STRING_LIST_PATHS = frozenset({"baselines.conditions", "statistical_design.pilot_fixture_ids"})
EVAL_MAPPING_PATHS = EVAL_MAPPING_SECTIONS | frozenset({
    "statistical_design.judging", "statistical_design.full_run_plan",
    "alternate_measurement_targets.output_contract_adherence",
})
EVAL_BOOLEAN_FIELDS = frozenset({
    "pilot_required", "randomize_condition_order", "rubric_blinding",
})
EVAL_NUMERIC_FIELDS = frozenset({
    "pilot_required_delta", "pilot_runs_per_condition", "bootstrap_replications",
    "runs_per_condition", "minimum_publishable_n", "temperature", "max_tokens",
    "count",
})

METADATA_PROFILE_KEYS = {
    "legacy-skill": (_fields("name skill fixture_type risk_tier expected_outputs"),),
    "suite-smoke": (_fields("name suite skill_under_test skill_type difficulty_tier provenance expected_behavior"),),
    "suite-risk": (
        _fields("name suite skill_under_test skill_type difficulty_tier provenance risk_class expected_wordpress_apis expected_verification_surfaces must_detect negative_space"),
        _fields("name suite skill_under_test skill_type difficulty_tier provenance risk_class expected_wordpress_surfaces expected_verification_surfaces must_detect negative_space"),
    ),
    "candidate-comparison": (_fields("name suite domain difficulty_tier provenance primary_skill_targets expected_behavior source_notes scenario_summary"),),
}
METADATA_SCALAR_FIELDS = frozenset({
    "name", "skill", "fixture_type", "risk_tier", "suite", "skill_under_test",
    "skill_type", "difficulty_tier", "provenance", "risk_class", "domain",
    "source_notes", "scenario_summary",
})
EXPECTATION_FIELDS = frozenset({
    "expected_outputs", "expected_behavior", "expected_wordpress_apis",
    "expected_wordpress_surfaces", "expected_verification_surfaces", "must_detect",
    "negative_space", "primary_skill_targets",
})

RUBRIC_PROFILE_KEYS = {
    "weighted": _fields("fixture skill_under_test max_score criteria"),
    "weighted-domain": _fields("fixture skill_under_test max_score criteria domain_signals"),
    "candidate-comparison": _fields("fixture scoring_method max_score criteria domain_signals discrimination_gate"),
}
CRITERION_KEYS = frozenset({
    "id", "weight", "description", "type", "category", "evidence_requirement",
})
WEIGHTED_CATEGORIES = frozenset({"quality", "false_positive_trap"})
DOMAIN_SIGNAL_KEYS = frozenset({
    "expected_wordpress_apis", "expected_surfaces", "must_detect",
    "must_not_claim", "must_not_penalize_or_do",
})


@dataclass(frozen=True)
class Issue:
    suite: str
    kind: str
    path: Path | None
    message: str


@dataclass(frozen=True)
class EvalConfig:
    fixture_directory: str
    fixture_count: int
    fixture_pattern: str
    metadata_suffix: str
    rubric_directory: str


class DuplicateKeyError(yaml.YAMLError):
    """Duplicate mapping key with a safe source location."""

    def __init__(self, mark: Any) -> None:
        super().__init__("duplicate mapping key")
        self.problem_mark = mark


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe loader that rejects duplicate keys before values can overwrite."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader, node: MappingNode, deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                "found an unhashable key", key_node.start_mark,
            ) from exc
        if duplicate:
            raise DuplicateKeyError(key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _location(exc_or_token: Any) -> str:
    mark = getattr(exc_or_token, "problem_mark", None)
    if mark is None:
        mark = getattr(exc_or_token, "start_mark", None)
    if mark is None:
        return "location unavailable"
    return f"line {mark.line + 1}, column {mark.column + 1}"


def _read_bounded_regular(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("document is not a regular non-symlink file")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read(MAX_YAML_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_yaml_document(
    path: Path, suite: str, document_kind: str,
) -> tuple[object | None, list[Issue]]:
    """Read one bounded, reference-free YAML document with unique keys."""
    try:
        encoded = _read_bounded_regular(path)
    except OSError:
        return None, [Issue(suite, f"invalid_{document_kind}_yaml", path, "document is unreadable")]
    if len(encoded) > MAX_YAML_BYTES:
        message = f"document exceeds the {MAX_YAML_BYTES}-byte limit"
        return None, [Issue(suite, f"invalid_{document_kind}_yaml", path, message)]
    try:
        text = encoded.decode("utf-8")
    except UnicodeError:
        return None, [Issue(suite, f"invalid_{document_kind}_yaml", path, "document is not valid UTF-8")]
    try:
        for token in yaml.scan(text, Loader=UniqueKeyLoader):
            if isinstance(token, (AliasToken, AnchorToken, TagToken)):
                message = f"YAML references and explicit tags are forbidden at {_location(token)}"
                return None, [Issue(suite, f"invalid_{document_kind}_yaml", path, message)]
        return yaml.load(text, Loader=UniqueKeyLoader), []
    except DuplicateKeyError as exc:
        message = f"duplicate mapping key at {_location(exc)}"
        return None, [Issue(suite, f"duplicate_{document_kind}_key", path, message)]
    except (yaml.YAMLError, RecursionError, ValueError, OverflowError) as exc:
        message = f"malformed YAML at {_location(exc)}"
        return None, [Issue(suite, f"invalid_{document_kind}_yaml", path, message)]


def match_eval_profiles(document: object) -> list[str]:
    if not isinstance(document, dict):
        return []
    keys = frozenset(document)
    return [name for name, expected in EVAL_PROFILE_KEYS.items() if keys == expected]


def match_metadata_profiles(document: object) -> list[str]:
    if not isinstance(document, dict):
        return []
    keys = frozenset(document) - {"runtime_assertions"}
    return [
        name for name, accepted in METADATA_PROFILE_KEYS.items()
        if any(keys == expected for expected in accepted)
    ]


def match_rubric_profiles(document: object) -> list[str]:
    if not isinstance(document, dict):
        return []
    keys = frozenset(document)
    return [name for name, expected in RUBRIC_PROFILE_KEYS.items() if keys == expected]


def _nonempty_string(value: object, limit: int = 4_096) -> bool:
    if type(value) is not str or not value.strip():
        return False
    try:
        return len(value.encode("utf-8")) <= limit
    except UnicodeError:
        return False


def _nonempty_string_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(_nonempty_string(item) for item in value)


def _positive_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value)) and value > 0
    except (OverflowError, ValueError):
        return False


def _nonnegative_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value)) and value >= 0
    except (OverflowError, ValueError):
        return False


def _safe_directory(value: object) -> str | None:
    if not _nonempty_string(value, 256) or "\x00" in value or "\\" in value:
        return None
    normalized = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    if any(character in normalized for character in "*?[]{}"):
        return None
    return normalized


def _safe_pattern(value: object, suffix: bool = False) -> bool:
    if not _nonempty_string(value, 128) or "\x00" in value:
        return False
    if "/" in value or "\\" in value or "**" in value or value in {".", ".."}:
        return False
    if suffix and (not value.startswith(".") or any(char in value for char in "*?[]{}")):
        return False
    return True


def _schema_issue(suite: str, kind: str, path: Path, message: str) -> Issue:
    return Issue(suite, kind, path, message)


def _validate_eval_tree(
    value: object, suite: str, path: Path, field: str, issues: list[Issue],
) -> None:
    if isinstance(value, dict):
        if field not in EVAL_MAPPING_PATHS:
            issues.append(_schema_issue(suite, "schema_eval_value", path, f"{field} must be a scalar"))
            return
        if not value or not all(_nonempty_string(key, 128) for key in value):
            issues.append(_schema_issue(suite, "schema_eval_value", path, f"{field} must be a keyed mapping"))
            return
        for key, child in value.items():
            _validate_eval_tree(child, suite, path, f"{field}.{key}", issues)
        return
    if isinstance(value, list):
        if field not in EVAL_STRING_LIST_PATHS or not _nonempty_string_list(value):
            issues.append(_schema_issue(suite, "schema_eval_value", path, f"{field} must be a nonempty string list"))
        return
    leaf = field.rsplit(".", 1)[-1]
    if leaf in EVAL_BOOLEAN_FIELDS:
        valid = type(value) is bool
    elif leaf in EVAL_NUMERIC_FIELDS:
        valid = _nonnegative_number(value)
    else:
        valid = _nonempty_string(value)
    if not valid:
        issues.append(_schema_issue(suite, "schema_eval_value", path, f"{field} has the wrong scalar type"))


def _validate_eval_sections(document: dict, suite: str, path: Path) -> list[Issue]:
    issues: list[Issue] = []
    for section in EVAL_MAPPING_SECTIONS & document.keys():
        if not isinstance(document[section], dict):
            issues.append(_schema_issue(suite, "schema_eval_section", path, f"{section} must be a mapping"))
        else:
            _validate_eval_tree(document[section], suite, path, section, issues)
    for section in EVAL_LIST_SECTIONS & document.keys():
        if not _nonempty_string_list(document[section]):
            issues.append(_schema_issue(suite, "schema_eval_section", path, f"{section} must be a string list"))
    return issues


def _validate_fixture_config(
    section: object, suite: str, path: Path,
) -> tuple[EvalConfig | None, list[Issue]]:
    issues: list[Issue] = []
    expected = {"directory", "count", "pattern", "metadata_suffix"}
    if not isinstance(section, dict):
        return None, issues
    if set(section) != expected:
        issues.append(_schema_issue(suite, "schema_eval_fixtures", path, "fixtures keys do not match the profile"))
    directory = _safe_directory(section.get("directory"))
    pattern = section.get("pattern")
    suffix = section.get("metadata_suffix")
    count = section.get("count")
    if directory is None:
        issues.append(_schema_issue(suite, "schema_eval_fixtures", path, "fixtures.directory is unsafe"))
    if not _safe_pattern(pattern):
        issues.append(_schema_issue(suite, "schema_eval_fixtures", path, "fixtures.pattern is unsafe"))
    if not _safe_pattern(suffix, suffix=True):
        issues.append(_schema_issue(suite, "schema_eval_fixtures", path, "fixtures.metadata_suffix is unsafe"))
    if type(count) is not int or count < 0:
        issues.append(_schema_issue(suite, "schema_eval_fixtures", path, "fixtures.count must be a nonnegative integer"))
    if issues:
        return None, issues
    return EvalConfig(directory, count, pattern, suffix, ""), []


def _validate_common_eval_maps(document: dict, suite: str, path: Path) -> list[Issue]:
    issues: list[Issue] = []
    skill = document.get("skill")
    if isinstance(skill, dict):
        expected_skill = {"name", "type", "description"} if "statistical_design" in document else {"name", "type", "status"}
        if set(skill) != expected_skill:
            issues.append(_schema_issue(suite, "schema_eval_identity", path, "skill keys do not match the named profile"))
        if not _nonempty_string(skill.get("name")) or skill.get("name") != suite:
            issues.append(_schema_issue(suite, "schema_eval_identity", path, "skill.name must match the suite"))
        if not _nonempty_string(skill.get("type")):
            issues.append(_schema_issue(suite, "schema_eval_identity", path, "skill.type is required"))
    baselines = document.get("baselines")
    if isinstance(baselines, dict):
        if set(baselines) != {"directory", "conditions"}:
            issues.append(_schema_issue(suite, "schema_eval_baselines", path, "baselines keys do not match the profile"))
        if _safe_directory(baselines.get("directory")) is None or not _nonempty_string_list(baselines.get("conditions")):
            issues.append(_schema_issue(suite, "schema_eval_baselines", path, "baselines values are invalid"))
    invocation = document.get("invocation")
    expected_invocation = {
        "model", "effort", "baseline_provider", "baseline_model_policy",
        "baseline_model", "baseline_effort", "note",
    }
    if isinstance(invocation, dict) and set(invocation) != expected_invocation:
        issues.append(_schema_issue(suite, "schema_eval_invocation", path, "invocation keys do not match the profile"))
    return issues


def validate_eval_config(
    document: object, suite: str, path: Path,
) -> tuple[EvalConfig | None, list[Issue]]:
    if not isinstance(document, dict):
        return None, [_schema_issue(suite, "schema_eval_root", path, "eval root must be a mapping")]
    issues = _validate_eval_sections(document, suite, path)
    matches = match_eval_profiles(document)
    if len(matches) != 1:
        issues.append(_schema_issue(suite, "schema_eval_profile", path, "eval document must match exactly one named profile"))
    issues.extend(_validate_common_eval_maps(document, suite, path))
    partial, fixture_issues = _validate_fixture_config(document.get("fixtures"), suite, path)
    issues.extend(fixture_issues)
    rubric_directory: str | None = None
    rubrics = document.get("rubrics")
    if isinstance(rubrics, dict):
        expected = {"directory", "scoring_method"}
        if matches == ["candidate-comparison"]:
            expected.add("primary_gate")
        if set(rubrics) != expected:
            issues.append(_schema_issue(suite, "schema_eval_rubrics", path, "rubrics keys do not match the profile"))
        rubric_directory = _safe_directory(rubrics.get("directory"))
        if rubric_directory is None or not _nonempty_string(rubrics.get("scoring_method")):
            issues.append(_schema_issue(suite, "schema_eval_rubrics", path, "rubrics values are invalid"))
    if issues or partial is None or rubric_directory is None:
        return None, issues
    return EvalConfig(
        partial.fixture_directory, partial.fixture_count, partial.fixture_pattern,
        partial.metadata_suffix, rubric_directory,
    ), []


def validate_metadata(
    document: object, suite: str, fixture: str, path: Path,
) -> list[Issue]:
    if not isinstance(document, dict):
        return [_schema_issue(suite, "schema_metadata_root", path, "metadata root must be a mapping")]
    issues: list[Issue] = []
    matches = match_metadata_profiles(document)
    if len(matches) != 1:
        issues.append(_schema_issue(suite, "schema_metadata_profile", path, "metadata must match one named profile"))
    if not _nonempty_string(document.get("name")) or document.get("name") != fixture:
        issues.append(_schema_issue(suite, "schema_metadata_name", path, "metadata name must match the fixture"))
    for field in METADATA_SCALAR_FIELDS & document.keys():
        if not _nonempty_string(document[field]):
            issues.append(_schema_issue(suite, "schema_metadata_scalar", path, f"{field} must be a nonempty string"))
    if "suite" in document and document.get("suite") != suite:
        issues.append(_schema_issue(suite, "schema_metadata_identity", path, "metadata suite must match its directory"))
    expectation_values = [document[field] for field in EXPECTATION_FIELDS & document.keys()]
    if not expectation_values or not all(_nonempty_string_list(value) for value in expectation_values):
        issues.append(_schema_issue(suite, "schema_metadata_expectations", path, "expectation lists must be substantive strings"))
    if "runtime_assertions" in document:
        try:
            values = document["runtime_assertions"]
            if not isinstance(values, dict):
                raise ValueError("runtime assertions must be a mapping")
            make_block_runtime_assertion(
                values.get("block_name"), values.get("frontend_selector"),
                values.get("expected_frontend_text"),
            )
            if set(values) != {"block_name", "frontend_selector", "expected_frontend_text"}:
                raise ValueError("runtime assertions contain unknown keys")
        except (TypeError, ValueError):
            issues.append(_schema_issue(suite, "schema_metadata_runtime_assertions", path, "runtime assertions violate the Plan 011 contract"))
    return issues


def _criterion_category(criterion: dict) -> str | None:
    type_value = criterion.get("type")
    category = criterion.get("category")
    if type_value is not None and not _nonempty_string(type_value):
        return None
    if category is not None and not _nonempty_string(category):
        return None
    if type_value is not None and category is not None and type_value != category:
        return None
    resolved = type_value if type_value is not None else category
    resolved = "quality" if resolved is None else resolved
    return resolved if resolved in WEIGHTED_CATEGORIES else None


def _validate_criterion(
    criterion: object, suite: str, path: Path, seen: set[str], issues: list[Issue],
) -> float | None:
    if not isinstance(criterion, dict) or not set(criterion).issubset(CRITERION_KEYS):
        issues.append(_schema_issue(suite, "schema_rubric_criteria", path, "criterion must use known mapping fields"))
        return None
    criterion_id = criterion.get("id")
    if not _nonempty_string(criterion_id, 256) or criterion_id in seen:
        issues.append(_schema_issue(suite, "schema_rubric_criterion_id", path, "criterion IDs must be unique nonempty strings"))
    else:
        seen.add(criterion_id)
    weight = criterion.get("weight")
    if not _positive_number(weight):
        issues.append(_schema_issue(suite, "schema_rubric_criterion_weight", path, "criterion weight must be positive and finite"))
        weight = None
    if not _nonempty_string(criterion.get("description")):
        issues.append(_schema_issue(suite, "schema_rubric_criterion_description", path, "criterion description is required"))
    if "evidence_requirement" in criterion and not _nonempty_string(criterion["evidence_requirement"]):
        issues.append(_schema_issue(suite, "schema_rubric_criterion_description", path, "evidence requirement must be a string"))
    if _criterion_category(criterion) is None:
        issues.append(_schema_issue(suite, "schema_rubric_criterion_category", path, "criterion category is invalid or conflicting"))
    return weight


def _validate_domain_signals(value: object, suite: str, path: Path) -> list[Issue]:
    valid = isinstance(value, dict) and bool(value) and set(value).issubset(DOMAIN_SIGNAL_KEYS)
    if valid:
        valid = all(_nonempty_string_list(item) for item in value.values())
    if valid:
        return []
    return [_schema_issue(suite, "schema_rubric_domain_signals", path, "domain signals must use known nonempty string lists")]


def _validate_discrimination_gate(value: object, suite: str, path: Path) -> list[Issue]:
    valid = isinstance(value, dict) and set(value) == {"required_delta", "fallback"}
    if valid:
        valid = _positive_number(value["required_delta"]) and _nonempty_string(value["fallback"])
    if valid:
        return []
    return [_schema_issue(suite, "schema_rubric_discrimination_gate", path, "discrimination gate has invalid fields")]


def validate_rubric(
    document: object, suite: str, fixture: str, path: Path,
) -> list[Issue]:
    if not isinstance(document, dict):
        return [_schema_issue(suite, "schema_rubric_root", path, "rubric root must be a mapping")]
    issues: list[Issue] = []
    if len(match_rubric_profiles(document)) != 1:
        issues.append(_schema_issue(suite, "schema_rubric_profile", path, "rubric must match one named profile"))
    if not _nonempty_string(document.get("fixture")) or document.get("fixture") != fixture:
        issues.append(_schema_issue(suite, "schema_rubric_fixture", path, "rubric fixture must match its filename"))
    for field in ("skill_under_test", "scoring_method"):
        if field in document and not _nonempty_string(document[field]):
            issues.append(_schema_issue(suite, "schema_rubric_identity", path, f"{field} must be a string"))
    maximum = document.get("max_score")
    if not _positive_number(maximum):
        issues.append(_schema_issue(suite, "schema_rubric_score", path, "max_score must be positive and finite"))
        maximum = None
    criteria = document.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        issues.append(_schema_issue(suite, "schema_rubric_criteria", path, "criteria must be a nonempty list"))
        criteria = []
    seen: set[str] = set()
    weights = [_validate_criterion(item, suite, path, seen, issues) for item in criteria]
    if maximum is not None and weights and all(weight is not None for weight in weights):
        try:
            total = math.fsum(weight for weight in weights if weight is not None)
        except OverflowError:
            total = math.inf
        if not math.isfinite(total) or not math.isclose(total, maximum, rel_tol=0.0, abs_tol=WEIGHT_TOLERANCE):
            issues.append(_schema_issue(suite, "schema_rubric_weight_sum", path, "criterion weights do not sum to max_score"))
    if "domain_signals" in document:
        issues.extend(_validate_domain_signals(document["domain_signals"], suite, path))
    if "discrimination_gate" in document:
        issues.extend(_validate_discrimination_gate(document["discrimination_gate"], suite, path))
    return issues


def parse_quality_gaps(
    path: Path = QUALITY_GAPS,
) -> tuple[set[tuple[str, str]], list[Issue]]:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return set(), []
    except OSError:
        mode = 0
    if not stat.S_ISREG(mode):
        return set(), [Issue("<global>", "schema_quality_gaps", path, "quality-gap ledger must be a regular file")]
    try:
        encoded = _read_bounded_regular(path)
        if len(encoded) > MAX_YAML_BYTES:
            raise OSError("quality-gap ledger exceeds its size limit")
        text = encoded.decode("utf-8")
    except (OSError, UnicodeError):
        return set(), [Issue("<global>", "schema_quality_gaps", path, "quality-gap ledger is unreadable or oversized")]
    known: set[tuple[str, str]] = set()
    pattern = re.compile(r"^\s*-\s+suite=(\S+)\s+scope=(\S+)\s+status=quarantined\b")
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            known.add((match.group(1), match.group(2)))
    return known, []


def metadata_stem(path: Path, suffix: str) -> str:
    return path.name[: -len(suffix)] if path.name.endswith(suffix) else path.stem


def check_placeholders(suite: str, path: Path, kind: str) -> list[Issue]:
    try:
        encoded = _read_bounded_regular(path)
        if len(encoded) > MAX_YAML_BYTES:
            raise OSError("document grew beyond its validated limit")
        text = encoded.decode("utf-8")
    except (OSError, UnicodeError):
        return [Issue(suite, f"invalid_{kind}_yaml", path, "document changed after schema validation")]
    hits = [marker for marker in PLACEHOLDER_MARKERS if marker in text]
    if not hits:
        return []
    message = f"placeholder marker(s): {', '.join(hits)}"
    return [Issue(suite, f"placeholder_{kind}", path, message)]


def _resolve_configured_directory(suite_dir: Path, relative: str) -> Path | None:
    declared = suite_dir / relative
    resolved_root = suite_dir.resolve()
    resolved = declared.resolve(strict=False)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        return None
    try:
        if declared.exists() and stat.S_ISLNK(declared.lstat().st_mode):
            return None
    except OSError:
        return None
    return declared


def _regular_paths(directory: Path, pattern: str) -> tuple[list[Path], list[Path]]:
    regular: list[Path] = []
    rejected: list[Path] = []
    for path in sorted(directory.glob(pattern)):
        try:
            mode = path.lstat().st_mode
        except OSError:
            rejected.append(path)
            continue
        (regular if stat.S_ISREG(mode) else rejected).append(path)
    return regular, rejected


def _pairing_issues(
    suite: str, fixture_dir: Path, rubric_dir: Path, stems: set[str],
    metadata: dict[str, Path], rubrics: dict[str, Path], suffix: str,
) -> list[Issue]:
    issues: list[Issue] = []
    for stem in sorted(stems - metadata.keys()):
        issues.append(Issue(suite, "missing_metadata", fixture_dir / f"{stem}{suffix}", "missing metadata for fixture"))
    for stem in sorted(metadata.keys() - stems):
        issues.append(Issue(suite, "extra_metadata", metadata[stem], "metadata has no matching fixture"))
    for stem in sorted(stems - rubrics.keys()):
        issues.append(Issue(suite, "missing_rubric", rubric_dir / f"{stem}.rubric.yaml", "missing rubric for fixture"))
    for stem in sorted(rubrics.keys() - stems):
        issues.append(Issue(suite, "extra_rubric", rubrics[stem], "rubric has no matching fixture"))
    return issues


def _validate_owned_documents(
    suite: str, metadata: dict[str, Path], rubrics: dict[str, Path],
) -> list[Issue]:
    issues: list[Issue] = []
    for stem, path in metadata.items():
        document, document_issues = read_yaml_document(path, suite, "metadata")
        issues.extend(document_issues)
        if document_issues:
            continue
        schema_issues = validate_metadata(document, suite, stem, path)
        issues.extend(schema_issues)
        if not schema_issues:
            issues.extend(check_placeholders(suite, path, "metadata"))
    for stem, path in rubrics.items():
        document, document_issues = read_yaml_document(path, suite, "rubric")
        issues.extend(document_issues)
        if document_issues:
            continue
        schema_issues = validate_rubric(document, suite, stem, path)
        issues.extend(schema_issues)
        if not schema_issues:
            issues.extend(check_placeholders(suite, path, "rubric"))
    return issues


def check_suite(suite_dir: Path) -> list[Issue]:
    suite = suite_dir.name
    config_path = suite_dir / "eval.yaml"
    document, issues = read_yaml_document(config_path, suite, "eval")
    if issues:
        return issues
    config, schema_issues = validate_eval_config(document, suite, config_path)
    if schema_issues or config is None:
        return schema_issues
    fixture_dir = _resolve_configured_directory(suite_dir, config.fixture_directory)
    rubric_dir = _resolve_configured_directory(suite_dir, config.rubric_directory)
    if fixture_dir is None or rubric_dir is None:
        return [_schema_issue(suite, "schema_eval_directory", config_path, "configured directory escapes or is a symlink")]
    if not fixture_dir.is_dir():
        return [Issue(suite, "missing_fixture_dir", fixture_dir, "configured fixtures directory does not exist")]
    if not rubric_dir.is_dir():
        return [Issue(suite, "missing_rubric_dir", rubric_dir, "configured rubrics directory does not exist")]
    fixtures, rejected_fixtures = _regular_paths(fixture_dir, config.fixture_pattern)
    metadata_paths, rejected_metadata = _regular_paths(fixture_dir, f"*{config.metadata_suffix}")
    rubric_paths, rejected_rubrics = _regular_paths(rubric_dir, "*.rubric.yaml")
    for rejected in rejected_fixtures + rejected_metadata + rejected_rubrics:
        issues.append(_schema_issue(suite, "schema_inventory_member", rejected, "inventory member must be a regular file"))
    stems = {path.stem for path in fixtures}
    if config.fixture_count != len(stems):
        issues.append(Issue(suite, "fixture_count_mismatch", config_path, f"declares {config.fixture_count} fixture(s), found {len(stems)}"))
    metadata = {metadata_stem(path, config.metadata_suffix): path for path in metadata_paths}
    rubrics = {path.name[: -len(".rubric.yaml")]: path for path in rubric_paths}
    issues.extend(_pairing_issues(suite, fixture_dir, rubric_dir, stems, metadata, rubrics, config.metadata_suffix))
    for path in sorted(fixture_dir.glob("*.rubric.yaml")):
        issues.append(Issue(suite, "misplaced_rubric", path, "rubric is in the fixtures directory"))
    issues.extend(_validate_owned_documents(suite, metadata, rubrics))
    return issues


def is_known(issue: Issue, known_gaps: set[tuple[str, str]]) -> bool:
    if issue.kind.startswith(STRUCTURAL_PREFIXES):
        return False
    if issue.kind.startswith("placeholder_"):
        return (issue.suite, "placeholder") in known_gaps
    return (issue.suite, issue.kind) in known_gaps


def rel(path: Path | None) -> str:
    if path is None:
        return "-"
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-suites", default=[], action="append",
        help="Suite names whose unacknowledged issues should fail; repeat or comma-separate.",
    )
    parser.add_argument(
        "--allow-known-gaps", action="store_true",
        help="Acknowledge quarantined content/inventory gaps, never structural YAML errors.",
    )
    return parser.parse_args()


def normalize_strict_suites(raw_values: list[str] | None) -> set[str]:
    return {
        item.strip() for value in (raw_values or []) for item in value.split(",")
        if item.strip()
    }


def collect_integrity_issues(
    strict_suites: set[str], suites_root: Path = SUITES_ROOT,
) -> list[Issue]:
    suite_dirs: dict[str, Path] = {}
    rejected: set[str] = set()
    issues: list[Issue] = []
    resolved_root = suites_root.resolve()
    for path in sorted(suites_root.iterdir()):
        try:
            mode = path.lstat().st_mode
        except OSError:
            continue
        if stat.S_ISLNK(mode):
            rejected.add(path.name)
            issues.append(Issue(path.name, "schema_suite_root", path, "suite root must not be a symlink"))
            continue
        if not stat.S_ISDIR(mode) or path.resolve().parent != resolved_root:
            continue
        try:
            (path / "eval.yaml").lstat()
        except OSError:
            continue
        suite_dirs[path.name] = path
    issues.extend([
        Issue(suite, "schema_strict_suite", suites_root / suite / "eval.yaml", "requested strict suite is missing")
        for suite in sorted(strict_suites - suite_dirs.keys() - rejected)
    ])
    for suite_dir in sorted(suite_dirs.values()):
        issues.extend(check_suite(suite_dir))
    return issues


def main() -> int:
    args = parse_args()
    strict_suites = normalize_strict_suites(args.strict_suites)
    known_gaps, gap_issues = parse_quality_gaps(QUALITY_GAPS) if args.allow_known_gaps else (set(), [])
    all_issues = gap_issues + collect_integrity_issues(strict_suites, SUITES_ROOT)
    if not all_issues:
        print("Eval suite integrity validation passed.")
        return 0
    print("Eval suite integrity issues:")
    failing = 0
    for issue in all_issues:
        known = is_known(issue, known_gaps)
        strict = issue.suite in strict_suites or bool(strict_suites and issue.kind == "schema_quality_gaps")
        status = "KNOWN" if known else ("ERROR" if strict else "REPORT")
        print(format_issue(issue, status))
        failing += int(strict and not known)
    if strict_suites and failing:
        print(f"\nStrict validation failed: {failing} unacknowledged issue(s).")
        return 1
    print("\nStrict validation passed for selected suites." if strict_suites else "\nReport mode complete; pass --strict-suites to fail on selected suites.")
    return 0


def _diagnostic_text(value: object) -> str:
    return ascii(str(value))[1:-1]


def format_issue(issue: Issue, status: str) -> str:
    values = (status, issue.suite, issue.kind, rel(issue.path), issue.message)
    safe = tuple(_diagnostic_text(value) for value in values)
    return f"  - [{safe[0]}] {safe[1]}: {safe[2]}: {safe[3]}: {safe[4]}"


if __name__ == "__main__":
    raise SystemExit(main())
