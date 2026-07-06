#!/usr/bin/env python3
"""Compile the MIT-licensed WordPress symbol snapshot for the API lint.

This is a maintainer-run generator, not a gate: it needs a PHP CLI and
(unless every input is supplied locally) network access. The lint
(`evals/harness/wp_api_lint.py`) only reads the committed snapshot.

Inputs and licensing (MIT only — see `docs/wordpress/reuse-ledger.md`):

- php-stubs/wordpress-stubs (MIT): function/class existence and
  `@deprecated` docblock data (deprecation version + successor API),
  introspected with PHP reflection.
- johnbillion/wp-compat symbols.json (MIT): per-function `since` versions.

Hook data is deliberately NOT compiled into this snapshot: the wp-hooks
JSON is GPL-3.0 and per the reuse ledger is consumed only inside the
Composer-fetched `evals/harness/php-tools/vendor/` tree at analysis time,
never committed or redistributed. `wp_api_lint.py` reads it from the vendor
tree directly when the toolchain is installed.

Usage (defaults fetch pinned upstream refs):

    python3 scripts/build-wp-symbol-db.py \
      --wp-version 7.0 \
      --out evals/harness/data/wp-symbols.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "evals" / "harness" / "data" / "wp-symbols.json"

DEFAULT_STUBS = "https://raw.githubusercontent.com/php-stubs/wordpress-stubs/v7.0.0/wordpress-stubs.php"
DEFAULT_WP_COMPAT = "https://raw.githubusercontent.com/johnbillion/wp-compat/trunk/symbols.json"

INTROSPECT_PHP = r"""<?php
$stubs = $argv[1];
$builtins = get_defined_functions()["internal"];
$before_classes = array_merge(get_declared_classes(), get_declared_interfaces(), get_declared_traits());
require $stubs;
$functions = [];
foreach (get_defined_functions()["user"] as $fn) {
    $entry = [];
    try {
        $doc = (string) (new ReflectionFunction($fn))->getDocComment();
    } catch (ReflectionException $e) {
        $doc = "";
    }
    if (preg_match('/@deprecated\s+(\d+[\d.]*)([^\n]*)/', $doc, $m)) {
        $entry["deprecated"] = $m[1];
        if (preg_match('/([A-Za-z_][A-Za-z0-9_:\\\\>-]*)\s*\(\)/', $m[2], $r)) {
            $entry["replacement"] = $r[1] . "()";
        }
    }
    $functions[strtolower($fn)] = empty($entry) ? new stdClass() : $entry;
}
$classes = [];
$after_classes = array_merge(get_declared_classes(), get_declared_interfaces(), get_declared_traits());
foreach (array_diff($after_classes, $before_classes) as $cls) {
    $classes[strtolower($cls)] = new stdClass();
}
echo json_encode([
    "php_builtins" => array_map("strtolower", $builtins),
    "functions" => $functions,
    "classes" => $classes,
]);
"""


def load_source(ref: str) -> bytes:
    if re.match(r"^https?://", ref):
        with urllib.request.urlopen(ref, timeout=120) as response:  # noqa: S310 - pinned refs
            return response.read()
    return Path(ref).read_bytes()


def introspect_stubs(stubs_bytes: bytes, php_bin: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="wp-symbol-db-") as tmp:
        tmp_path = Path(tmp)
        stubs_file = tmp_path / "wordpress-stubs.php"
        stubs_file.write_bytes(stubs_bytes)
        script_file = tmp_path / "introspect.php"
        script_file.write_text(INTROSPECT_PHP, encoding="utf-8")
        proc = subprocess.run(
            [php_bin, "-d", "memory_limit=1G", str(script_file), str(stubs_file)],
            capture_output=True,
            text=True,
            timeout=600,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"PHP introspection failed (exit {proc.returncode}): {proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stubs", default=DEFAULT_STUBS, help="wordpress-stubs.php path or URL")
    parser.add_argument("--wp-compat", default=DEFAULT_WP_COMPAT, help="wp-compat symbols.json path or URL")
    parser.add_argument("--wp-version", required=True, help="WordPress version label for the snapshot, e.g. 7.0")
    parser.add_argument("--php-bin", default="php")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    introspected = introspect_stubs(load_source(args.stubs), args.php_bin)

    wp_compat = json.loads(load_source(args.wp_compat))
    functions = introspected["functions"]
    for symbol, meta in wp_compat.get("symbols", {}).items():
        if "::" in symbol:
            continue  # methods are out of scope for the native engine
        since = meta.get("since")
        name = symbol.lower()
        if since and name in functions:
            functions[name] = dict(functions[name] or {})
            functions[name]["since"] = since

    snapshot = {
        "schema_version": 1,
        "wp_version": args.wp_version,
        "sources": {
            "wordpress_stubs": {"ref": args.stubs, "license": "MIT"},
            "wp_compat": {"ref": args.wp_compat, "license": "MIT"},
        },
        "php_builtins": sorted(set(introspected["php_builtins"])),
        "functions": {name: functions[name] or {} for name in sorted(functions)},
        "classes": {name: introspected["classes"][name] or {} for name in sorted(introspected["classes"])},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Wrote {out_path} — WP {args.wp_version}: "
        f"{len(snapshot['functions'])} functions, {len(snapshot['classes'])} classes, "
        f"{len(snapshot['php_builtins'])} PHP builtins (MIT sources only; hooks stay vendor-side)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
