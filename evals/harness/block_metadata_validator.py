"""Shared static contract checks for WordPress block metadata artifacts."""
from __future__ import annotations

import json
import re
import shlex
from collections import deque
from dataclasses import dataclass
from itertools import islice
from pathlib import PurePosixPath
from typing import Mapping


MAX_METADATA_BYTES = 1024 * 1024
MAX_BLOCK_METADATA_FILES = 128
MAX_BLOCK_METADATA_TOTAL_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 100_000
# This is a structural integer bound, not a claim about the current WordPress API.
MAX_STRUCTURAL_API_VERSION = 65_535
MAX_PHP_REGISTRATION_FILES = 256
MAX_PHP_REGISTRATION_FILE_BYTES = 1024 * 1024
MAX_PHP_REGISTRATION_TOTAL_BYTES = 8 * 1024 * 1024
MAX_PHP_REGISTRATION_TOKENS = 250_000
IGNORED_METADATA_ROOTS = {
    ".git",
    ".wp-env",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "vendor",
}
ASSET_FIELDS = (
    "editorScript",
    "script",
    "viewScript",
    "viewScriptModule",
    "editorStyle",
    "style",
    "viewStyle",
)
REQUIRED_STRING_FIELDS = ("name", "title", "category")
OBJECT_FIELDS = ("attributes", "supports", "providesContext", "example")
BLOCK_NAME_RE = re.compile(
    r"^[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*$"
)
BUILD_PATH_RE = re.compile(r"^[A-Za-z0-9_./@,+-]+$")
BUILD_BOOLEAN_FLAGS = frozenset({
    "--experimental-modules",
    "--webpack-copy-php",
    "--webpack-no-externals",
    "--blocks-manifest",
    "--webpack-bundle-analyzer",
})
BUILD_PATH_FLAGS = ("--source-path=", "--output-path=")
PHP_OPEN_RE = re.compile(r"<\?(?:php\b|=)", re.IGNORECASE)
PHP_HEREDOC_RE = re.compile(
    r"<<<[ \t]*(?P<quote>['\"]?)(?P<label>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P=quote)[ \t]*(?:\r\n|\n|\r)"
)
PHP_IDENTIFIER_RE = re.compile(r"[A-Za-z_\x80-\xff][A-Za-z0-9_\x80-\xff]*")
EXTERNAL_ASSET_ID_RE = re.compile(
    r"^@?[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*$"
)
ASSET_FILE_SUFFIXES = (".js", ".mjs", ".cjs", ".css", ".scss", ".php")


@dataclass(frozen=True)
class BlockValidationCheck:
    id: str
    status: str
    detail: str


def _check(check_id: str, passed: bool, detail: str) -> BlockValidationCheck:
    return BlockValidationCheck(check_id, "pass" if passed else "fail", detail)


def _reject_constant(value: str):
    raise ValueError(f"JSON constant is forbidden: {value}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_string_error(value: str) -> str | None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        return "JSON strings must contain Unicode scalar values"
    return None


def _json_shape_error(value) -> str | None:
    stack = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            return f"JSON value exceeds {MAX_JSON_NODES} nodes"
        if depth > MAX_JSON_DEPTH:
            return f"JSON value exceeds depth {MAX_JSON_DEPTH}"
        if isinstance(current, str):
            error = _json_string_error(current)
            if error:
                return error
        elif isinstance(current, dict):
            for key, child in current.items():
                error = _json_string_error(key)
                if error:
                    return error
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)
    return None


def _load_object(path: str, content: bytes) -> tuple[dict | None, str | None]:
    if len(content) > MAX_METADATA_BYTES:
        return None, f"{path} exceeds the 1 MiB metadata limit"
    try:
        text = content.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        return None, f"{path} is invalid strict JSON: {exc}"
    if not isinstance(value, dict):
        return None, f"{path} must contain a JSON object"
    shape_error = _json_shape_error(value)
    if shape_error:
        return None, f"{path} is outside the bounded JSON contract: {shape_error}"
    return value, None


def _is_ignored_metadata(path: str) -> bool:
    return any(part in IGNORED_METADATA_ROOTS for part in PurePosixPath(path).parts)


def _parse_metadata(files: Mapping[str, bytes]):
    candidates = tuple(
        path
        for path in sorted(files)
        if PurePosixPath(path).name == "block.json"
        and not _is_ignored_metadata(path)
    )
    if len(candidates) > MAX_BLOCK_METADATA_FILES:
        return candidates, (), (
            f"block metadata count exceeds {MAX_BLOCK_METADATA_FILES} files",
        )
    metadata_bytes = sum(len(files[path]) for path in candidates)
    if metadata_bytes > MAX_BLOCK_METADATA_TOTAL_BYTES:
        return candidates, (), ("block metadata exceeds the 8 MiB aggregate limit",)
    parsed = []
    errors = []
    for path in candidates:
        value, error = _load_object(path, files[path])
        if error:
            errors.append(error)
        else:
            parsed.append((path, value))
    return candidates, tuple(parsed), tuple(errors)


def _metadata_check(candidates, errors) -> BlockValidationCheck:
    if not candidates:
        return _check("block_metadata", False, "no block.json file found")
    if errors:
        return _check("block_metadata", False, "; ".join(errors))
    return _check(
        "block_metadata",
        True,
        f"{len(candidates)} block.json file(s) parsed as strict JSON objects",
    )


def _name_check(records) -> BlockValidationCheck:
    errors = []
    first_path_by_name = {}
    for path, metadata in records:
        name = metadata.get("name")
        if not isinstance(name, str) or not BLOCK_NAME_RE.fullmatch(name):
            errors.append(f"{path} name must be lowercase namespace/block-name")
            continue
        if name in first_path_by_name:
            errors.append(
                f"{path} duplicates block name {name} from "
                f"{first_path_by_name[name]}"
            )
        else:
            first_path_by_name[name] = path
    return _check(
        "block_metadata_name",
        not errors,
        "; ".join(errors)
        or "all block names are unique and use namespace/block-name syntax",
    )


def _type_errors(path: str, metadata: dict) -> list[str]:
    errors = []
    for field in REQUIRED_STRING_FIELDS:
        value = metadata.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{path} {field} must be a non-empty string")
    for field in OBJECT_FIELDS:
        if field in metadata and not isinstance(metadata[field], dict):
            errors.append(f"{path} {field} must be an object")
    return errors


def _types_check(records) -> BlockValidationCheck:
    errors = [error for path, value in records for error in _type_errors(path, value)]
    return _check(
        "block_metadata_types",
        not errors,
        "; ".join(errors) or "required strings and optional object fields have valid types",
    )


def _api_version_check(records) -> BlockValidationCheck:
    errors = []
    for path, metadata in records:
        value = metadata.get("apiVersion")
        if type(value) is not int or not 1 <= value <= MAX_STRUCTURAL_API_VERSION:
            errors.append(
                f"{path} apiVersion must be an integer from 1 to "
                f"{MAX_STRUCTURAL_API_VERSION}"
            )
    detail = (
        "; ".join(errors)
        or "apiVersion values satisfy a positive structural integer bound; "
        "this does not assert current WordPress support"
    )
    return _check("block_metadata_api_version", not errors, detail)


def _field_values(path: str, field: str, value) -> tuple[tuple[str, ...], str | None]:
    if isinstance(value, str):
        return (value,), None
    if not isinstance(value, list) or not value:
        return (), f"{path} {field} must be a string or non-empty flat string array"
    if any(not isinstance(item, str) for item in value):
        return (), f"{path} {field} must be a flat string array"
    return tuple(value), None


def _resolve_local(metadata_path: str, value: str, available: frozenset[str]):
    raw = value[len("file:") :]
    if not raw:
        return None, "has an empty file target"
    if raw.startswith("/"):
        return None, "uses an absolute file target"
    if "\\" in raw:
        return None, "uses a backslash file target"
    if ":" in raw:
        return None, "uses a scheme-like file target"
    if any(ord(character) < 32 for character in raw):
        return None, "uses a control character in a file target"
    parts = list(PurePosixPath(metadata_path).parent.parts)
    for part in PurePosixPath(raw).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None, "escapes the artifact root"
            parts.pop()
        else:
            parts.append(part)
    target = PurePosixPath(*parts).as_posix()
    if target not in available:
        return target, f"references missing local file {target}"
    return target, None


def _handle_error(value: str) -> str | None:
    if not value or value != value.strip():
        return "registered handle must be non-empty without surrounding whitespace"
    if any(ord(character) < 32 for character in value):
        return "registered handle contains a control character"
    if len(value.encode("utf-8")) > 128 or not EXTERNAL_ASSET_ID_RE.fullmatch(value):
        return "external handle/module ID must use a bounded token grammar"
    if value.endswith(ASSET_FILE_SUFFIXES):
        return "registered handle looks like an asset path missing the file: prefix"
    return None


def _asset_field_errors(path, metadata, available):
    errors = []
    local_count = 0
    handle_count = 0
    for field in ASSET_FIELDS:
        if field not in metadata:
            continue
        values, shape_error = _field_values(path, field, metadata[field])
        if shape_error:
            errors.append(shape_error)
            continue
        for value in values:
            if value.startswith("file:"):
                _target, error = _resolve_local(path, value, available)
                local_count += 1
            else:
                error = _handle_error(value)
                handle_count += 1
            if error:
                errors.append(f"{path} {field} {error}")
    return errors, local_count, handle_count


def _php_field_errors(path, metadata, available):
    errors = []
    local_count = 0
    if "render" in metadata:
        value = metadata["render"]
        if not isinstance(value, str) or not value.startswith("file:"):
            errors.append(f"{path} render must be one scalar file: target")
        else:
            _target, error = _resolve_local(path, value, available)
            local_count += 1
            if error:
                errors.append(f"{path} render {error}")
    variations = metadata.get("variations")
    if variations is not None and not isinstance(variations, list):
        if not isinstance(variations, str) or not variations.startswith("file:"):
            errors.append(f"{path} variations must be an inline array or file: target")
        else:
            _target, error = _resolve_local(path, variations, available)
            local_count += 1
            if error:
                errors.append(f"{path} variations {error}")
    return errors, local_count


def _file_references_check(records, files) -> BlockValidationCheck:
    errors = []
    local_count = 0
    handle_count = 0
    available = frozenset(files)
    for path, metadata in records:
        asset_errors, asset_local, asset_handles = _asset_field_errors(
            path, metadata, available
        )
        php_errors, php_local = _php_field_errors(path, metadata, available)
        errors.extend(asset_errors + php_errors)
        local_count += asset_local + php_local
        handle_count += asset_handles
    detail = (
        "; ".join(errors)
        or f"validated {local_count} local file reference(s) and "
        f"{handle_count} external handle/module ID reference(s); external "
        "registration is not statically proven"
    )
    return _check("block_metadata_file_references", not errors, detail)


def _skip_php_quoted(text: str, start: int) -> int:
    quote = text[start]
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == quote:
            return index + 1
        else:
            index += 1
    return len(text)


def _skip_php_heredoc(text: str, start: int) -> int | None:
    match = PHP_HEREDOC_RE.match(text, start)
    if match is None:
        return None
    closing = re.compile(
        rf"(?m)^[ \t]*{re.escape(match.group('label'))};?[ \t]*(?:\r?$)"
    ).search(text, match.end())
    if closing is None:
        return len(text)
    newline = text.find("\n", closing.end())
    return len(text) if newline < 0 else newline + 1


def _skip_php_line_comment(text: str, start: int) -> tuple[int, bool]:
    newline = text.find("\n", start + 1)
    closing = text.find("?>", start + 1)
    if closing >= 0 and (newline < 0 or closing < newline):
        return closing + 2, False
    return (len(text) if newline < 0 else newline + 1), True


def _iter_php_code_tokens(text: str):
    """Yield lexical tokens from real PHP regions with constant retention."""
    index = 0
    in_php = False
    while index < len(text):
        if not in_php:
            opening = PHP_OPEN_RE.search(text, index)
            if opening is None:
                break
            index = opening.end()
            in_php = True
            continue
        if text.startswith("?>", index):
            index += 2
            in_php = False
        elif text.startswith("//", index) or text[index] == "#":
            index, in_php = _skip_php_line_comment(text, index)
        elif text.startswith("/*", index):
            closing = text.find("*/", index + 2)
            index = len(text) if closing < 0 else closing + 2
        elif text[index] in "'\"`":
            index = _skip_php_quoted(text, index)
        elif text.startswith("<<<", index):
            heredoc_end = _skip_php_heredoc(text, index)
            if heredoc_end is None:
                yield "<"
                index += 1
            else:
                index = heredoc_end
        else:
            identifier = PHP_IDENTIFIER_RE.match(text, index)
            if identifier:
                yield identifier.group()
                index = identifier.end()
            elif text.startswith(("?->",), index):
                yield "?->"
                index += 3
            elif text.startswith(("->", "::", "=>", "&&", "||", "??"), index):
                yield text[index : index + 2]
                index += 2
            elif not text[index].isspace():
                yield text[index]
                index += 1
            else:
                index += 1


def _token_windows(tokens, width: int = 6):
    iterator = iter(tokens)
    buffered = deque(islice(iterator, width))
    while buffered:
        current = buffered.popleft()
        yield current, tuple(buffered)
        try:
            buffered.append(next(iterator))
        except StopIteration:
            pass


NON_CALL_PREFIXES = frozenset({
    "function", "fn", "new", "class", "interface", "trait", "enum",
    "->", "?->", "::", "$",
})
ROOT_CALL_PREFIXES = frozenset({
    "(", "[", "{", "=", ",", ";", ":", "?", "!", "&&", "||", "??",
    "=>", "return", "echo", "print", "yield", "throw",
})


def _registration_call_kind(previous, future) -> str | None:
    if not future or future[0] != "(":
        return None
    if tuple(future[:5]) == ("(", ".", ".", ".", ")"):
        return None
    prior = previous[-1] if previous else None
    before = previous[-2] if len(previous) > 1 else None
    if prior in NON_CALL_PREFIXES or (prior == "&" and before in {"function", "fn"}):
        return None
    if prior != "\\":
        return "unqualified"
    if before is None or before in ROOT_CALL_PREFIXES:
        return "qualified"
    return None


def _scan_php_registration(text: str, token_budget: int):
    previous = deque(maxlen=4)
    qualified = unqualified = local_shadow = import_shadow = False
    namespace = named_namespace = global_namespace = False
    use_pending = use_function = False
    count = 0
    for token, future in _token_windows(_iter_php_code_tokens(text)):
        count += 1
        if count > token_budget:
            return False, count, "PHP registration scan exceeds token budget"
        lowered = token.lower() if PHP_IDENTIFIER_RE.fullmatch(token) else token
        if lowered == "namespace":
            namespace = True
            if future and future[0] == "{":
                global_namespace = True
            else:
                named_namespace = True
        if lowered == "use":
            use_pending = True
        elif use_pending and lowered == "function":
            use_pending = False
            use_function = True
        elif token == ";":
            use_pending = use_function = False
        if lowered == "register_block_type":
            prior = previous[-1] if previous else None
            before = previous[-2] if len(previous) > 1 else None
            local_shadow |= prior == "function" or (
                prior == "&" and before == "function"
            )
            import_shadow |= use_function
            kind = _registration_call_kind(previous, future)
            qualified |= kind == "qualified"
            unqualified |= kind == "unqualified"
        previous.append(lowered)
        if tuple(previous) == ("__halt_compiler", "(", ")", ";"):
            break
    facts = {
        "qualified_candidate": qualified,
        "unqualified_candidate": (
            unqualified and not namespace and not local_shadow and not import_shadow
        ),
        "global_shadow": local_shadow and (
            not named_namespace or global_namespace
        ),
    }
    return facts, count, None


def _php_registration(files: Mapping[str, bytes]):
    paths = [
        path for path in sorted(files)
        if PurePosixPath(path).suffix.lower() == ".php"
        and not _is_ignored_metadata(path)
    ]
    if len(paths) > MAX_PHP_REGISTRATION_FILES:
        return None, f"PHP registration scan exceeds {MAX_PHP_REGISTRATION_FILES} files"
    total_bytes = 0
    remaining_tokens = MAX_PHP_REGISTRATION_TOKENS
    qualified_candidates = []
    unqualified_candidates = []
    global_shadow = False
    for path in paths:
        content = files[path]
        if len(content) > MAX_PHP_REGISTRATION_FILE_BYTES:
            return None, f"{path} exceeds the 1 MiB PHP registration scan limit"
        total_bytes += len(content)
        if total_bytes > MAX_PHP_REGISTRATION_TOTAL_BYTES:
            return None, "PHP registration scan exceeds the 8 MiB total limit"
        text = content.decode("utf-8", errors="replace")
        facts, used, error = _scan_php_registration(text, remaining_tokens)
        remaining_tokens -= used
        if error:
            return None, error
        if facts["qualified_candidate"]:
            qualified_candidates.append(path)
        if facts["unqualified_candidate"]:
            unqualified_candidates.append(path)
        global_shadow |= facts["global_shadow"]
    if global_shadow:
        return None, "artifact declares a global register_block_type() shadow"
    candidates = qualified_candidates or unqualified_candidates
    return (candidates[0], None) if candidates else (None, None)


def _safe_build_path(value: str) -> bool:
    if not value or not BUILD_PATH_RE.fullmatch(value):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def _admitted_build_command(command: str) -> tuple[bool, str | None]:
    if any(ord(character) < 32 for character in command):
        return False, "scripts.build contains a forbidden control character"
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as exc:
        return False, f"scripts.build has invalid shell quoting: {exc}"
    if tokens[:2] != ["wp-scripts", "build"]:
        return False, "scripts.build must start with wp-scripts build"
    seen_flags = set()
    for token in tokens[2:]:
        if token in BUILD_BOOLEAN_FLAGS:
            key = token
        elif any(token.startswith(prefix) for prefix in BUILD_PATH_FLAGS):
            key, value = token.split("=", 1)
            if not _safe_build_path(value):
                return False, f"scripts.build has unsafe path flag {key}"
        elif token.startswith("-"):
            return False, f"scripts.build uses unsupported option {token}"
        elif not _safe_build_path(token):
            return False, "scripts.build has an unsafe positional entry path"
        else:
            continue
        if key in seen_flags:
            return False, f"scripts.build repeats option {key}"
        seen_flags.add(key)
    return True, None


def _package_build(files: Mapping[str, bytes]) -> tuple[bool, str]:
    package = files.get("package.json")
    if package is None:
        return False, "root package.json is absent"
    data, error = _load_object("package.json", package)
    if error:
        return False, error
    scripts = data.get("scripts")
    build = scripts.get("build") if isinstance(scripts, dict) else None
    if not isinstance(build, str):
        return False, "scripts.build is not a string"
    admitted, command_error = _admitted_build_command(build)
    if not admitted:
        return False, command_error or "scripts.build is not admitted"
    dependencies = {}
    for field in ("dependencies", "devDependencies"):
        value = data.get(field)
        if isinstance(value, dict):
            dependencies.update(value)
    version = dependencies.get("@wordpress/scripts")
    if not isinstance(version, str) or not version.strip():
        return False, "@wordpress/scripts is absent from dependencies"
    return True, (
        "root package.json has an admitted @wordpress/scripts build entrypoint; "
        "WordPress block registration is not statically proven and remains a "
        "runtime/host-integration gate; dependency locking remains a runtime-profile gate"
    )


def _registration_check(files: Mapping[str, bytes]) -> BlockValidationCheck:
    admitted, build_detail = _package_build(files)
    if admitted:
        return _check("block_registration", True, build_detail)
    php_path, scan_error = _php_registration(files)
    if php_path:
        return _check(
            "block_registration",
            True,
            f"syntactically unambiguous global register_block_type() call found in {php_path}",
        )
    detail = scan_error or (
        "no syntactically unambiguous global register_block_type() call; "
        f"build entrypoint rejected: {build_detail}"
    )
    return _check("block_registration", False, detail)


def _unparsed_check(check_id: str, errors) -> BlockValidationCheck:
    reason = "; ".join(errors) or "no parsed block.json metadata is available"
    return _check(check_id, False, f"cannot validate because {reason}")


def validate_block_artifact(
    files: Mapping[str, bytes],
) -> tuple[BlockValidationCheck, ...]:
    """Validate block metadata and registration from an immutable byte view."""
    normalized = {
        PurePosixPath(path).as_posix(): bytes(content)
        for path, content in files.items()
    }
    candidates, records, errors = _parse_metadata(normalized)
    metadata = _metadata_check(candidates, errors)
    if metadata.status == "pass":
        dependent = (
            _name_check(records),
            _types_check(records),
            _api_version_check(records),
            _file_references_check(records, normalized),
        )
    else:
        dependent = tuple(
            _unparsed_check(check_id, errors)
            for check_id in (
                "block_metadata_name",
                "block_metadata_types",
                "block_metadata_api_version",
                "block_metadata_file_references",
            )
        )
    return (metadata, *dependent, _registration_check(normalized))
