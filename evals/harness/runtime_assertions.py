"""Strict fixture-pair loading for conditional isolated block runtime proof."""
from __future__ import annotations

import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

from wp_runtime_types import BlockRuntimeAssertion


SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
BLOCK_NAME = re.compile(r"[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*")
SELECTOR = re.compile(r"[.][A-Za-z][A-Za-z0-9_-]{0,127}")
ASSERTION_KEYS = frozenset({
    "block_name", "frontend_selector", "expected_frontend_text",
})


@dataclass(frozen=True)
class FixtureAssertionPair:
    fixture_path: Path
    metadata_path: Path
    assertion: BlockRuntimeAssertion


def _safe_member(root: Path, suite: str, fixture: str, suffix: str) -> Path:
    if not SAFE_ID.fullmatch(suite) or not SAFE_ID.fullmatch(fixture):
        raise ValueError("suite and fixture must be safe identifiers")
    declared = root / suite / "fixtures" / f"{fixture}{suffix}"
    resolved_root = root.resolve()
    resolved = declared.resolve(strict=False)
    if resolved_root not in resolved.parents:
        raise ValueError("fixture pair containment check failed")
    try:
        mode = declared.lstat().st_mode
    except OSError as exc:
        raise ValueError(f"fixture pair member is missing: {declared.name}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError(f"fixture pair member must be a regular non-symlink file: {declared.name}")
    if resolved != declared.absolute():
        raise ValueError("fixture pair containment check failed")
    return resolved


def _required_strings(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != ASSERTION_KEYS:
        raise ValueError("runtime_assertions must contain exactly the three reviewed keys")
    if not all(type(item) is str for item in value.values()):
        raise ValueError("runtime assertion values must each be a string")
    return value


def _validate_block_name(value: str) -> str:
    if len(value.encode("utf-8")) > 128:
        raise ValueError("runtime block_name exceeds 128 UTF-8 bytes")
    if BLOCK_NAME.fullmatch(value) is None:
        raise ValueError("runtime block_name is not a WordPress namespace/name")
    return value


def _validate_selector(value: str, block_name: str) -> str:
    if SELECTOR.fullmatch(value) is None:
        raise ValueError("runtime frontend selector is unsafe")
    expected = ".wp-block-" + block_name.replace("/", "-")
    if value != expected:
        raise ValueError("runtime frontend selector is not the deterministic WordPress wrapper")
    return value


def _validate_text(value: str) -> str:
    if value != value.strip():
        raise ValueError("runtime expected text has leading or trailing whitespace")
    if not 1 <= len(value) <= 500:
        raise ValueError("runtime expected text must contain 1-500 characters")
    if len(value.encode("utf-8", errors="surrogatepass")) > 2_000:
        raise ValueError("runtime expected text exceeds 2,000 UTF-8 bytes")
    categories = {unicodedata.category(character) for character in value}
    if "Cs" in categories:
        raise ValueError("runtime expected text contains a surrogate")
    if "Cc" in categories:
        raise ValueError("runtime expected text contains a control character")
    if "Cf" in categories:
        raise ValueError("runtime expected text contains a format character")
    if "<" in value or ">" in value:
        raise ValueError("runtime expected text must be literal non-HTML text")
    return value


def make_block_runtime_assertion(
    block_name: str | None, frontend_selector: str | None,
    expected_frontend_text: str | None,
) -> BlockRuntimeAssertion:
    values = _required_strings({
        "block_name": block_name,
        "frontend_selector": frontend_selector,
        "expected_frontend_text": expected_frontend_text,
    })
    name = _validate_block_name(values["block_name"])
    return BlockRuntimeAssertion(
        name, _validate_selector(values["frontend_selector"], name),
        _validate_text(values["expected_frontend_text"]),
    )


def load_block_runtime_fixture(
    suites_root: Path, suite: str, fixture: str,
) -> FixtureAssertionPair:
    """Load one exact fixture/metadata pair and its strict assertion contract."""
    fixture_path = _safe_member(suites_root, suite, fixture, ".md")
    metadata_path = _safe_member(suites_root, suite, fixture, ".metadata.yaml")
    try:
        metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("fixture runtime metadata is unreadable or malformed") from exc
    if not isinstance(metadata, dict):
        raise ValueError("fixture runtime metadata must be a mapping")
    if metadata.get("name") != fixture or metadata.get("suite") != suite:
        raise ValueError("fixture metadata identity mismatch")
    values = _required_strings(metadata.get("runtime_assertions"))
    assertion = make_block_runtime_assertion(
        values["block_name"], values["frontend_selector"],
        values["expected_frontend_text"],
    )
    return FixtureAssertionPair(fixture_path, metadata_path, assertion)
