"""Hermetic provenance checks for the committed WordPress symbol snapshot."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_PATH = ROOT / "evals" / "harness" / "data" / "wp-symbols.json"


def load_builder():
    path = ROOT / "scripts" / "build-wp-symbol-db.py"
    spec = importlib.util.spec_from_file_location("build_wp_symbol_db", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def snapshot():
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_committed_symbol_snapshot_has_lock_matched_durable_provenance():
    builder = load_builder()

    builder.validate_snapshot(snapshot())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data["sources"]["wordpress_stubs"].update(url="/tmp/stubs.php"), "immutable URL"),
        (lambda data: data["sources"]["wp_compat"].update(url="https://raw.githubusercontent.com/johnbillion/wp-compat/trunk/symbols.json"), "immutable URL"),
        (lambda data: data["sources"]["wordpress_stubs"].pop("sha256"), "source metadata"),
        (lambda data: data["sources"]["wp_compat"].update(version="0.0.0"), "Composer lock"),
        (lambda data: data.update(wp_version="6.9"), "WordPress version"),
        (lambda data: data["generator"]["container"].update(index="sha256:" + "0" * 64), "container inventory"),
        (lambda data: data["generator"].update(version=2), "generator metadata"),
        (lambda data: data["php_builtins"].append(data["php_builtins"][0]), "duplicate"),
        (lambda data: data["generator"].update(symbols_sha256="0" * 64), "symbol digest"),
    ],
)
def test_snapshot_validation_fails_closed(mutation, message):
    builder = load_builder()
    changed = copy.deepcopy(snapshot())
    mutation(changed)

    with pytest.raises(ValueError, match=message):
        builder.validate_snapshot(changed)
