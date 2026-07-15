"""One canonical generated block wrapper shared by synthesis and validation."""
from __future__ import annotations

import re
from pathlib import PurePosixPath


TEXTDOMAIN_LINE = re.compile(rb"(?m)^ \* Text Domain: ([a-z0-9][a-z0-9-]*)$")


def _safe_textdomain(value: str) -> str:
    if (
        not isinstance(value, str) or not value or len(value) > 200
        or re.fullmatch(r"[a-z0-9][a-z0-9-]*", value) is None
    ):
        raise ValueError("wrapper textdomain is not a safe slug")
    return value


def _safe_selected_path(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("wrapper selected path must be a string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("wrapper selected path contains a control character")
    path = PurePosixPath(value)
    if (
        not value or path.is_absolute() or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("wrapper selected path is not normalized and safe")
    return value


def php_single_quoted_literal(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("PHP literal value must be a string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("PHP literal path contains a control character")
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def build(textdomain: str, selected_block_json: str) -> bytes:
    textdomain = _safe_textdomain(textdomain)
    selected = _safe_selected_path(selected_block_json)
    literal = php_single_quoted_literal(f"/generated/{selected}")
    return f"""<?php
/**
 * Plugin Name: Generated Block Runtime Wrapper
 * Version: 0.1.0
 * Text Domain: {textdomain}
 * License: GPL-2.0-or-later
 */
if ( ! defined( 'ABSPATH' ) ) {{ exit; }}
add_action( 'init', 'generated_block_runtime_wrapper_register_block' );
function generated_block_runtime_wrapper_register_block(): void {{
\tregister_block_type( __DIR__ . {literal} );
}}
""".encode("utf-8")


def validate(wrapper_bytes: bytes, selected_block_json: str) -> None:
    if not isinstance(wrapper_bytes, bytes) or not wrapper_bytes:
        raise ValueError("wrapper bytes are empty or invalid")
    matches = TEXTDOMAIN_LINE.findall(wrapper_bytes)
    if len(matches) != 1:
        raise ValueError("wrapper does not contain one canonical textdomain")
    try:
        textdomain = matches[0].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("wrapper textdomain is not ASCII") from exc
    if wrapper_bytes != build(textdomain, selected_block_json):
        raise ValueError("wrapper does not contain the exact registration bootstrap")
