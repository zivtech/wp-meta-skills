#!/usr/bin/env python3
"""Bounded system-curl transport with no ambient configuration or secret argv."""
from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import SplitResult, urlsplit


_CURL_CANDIDATES = (Path("/usr/bin/curl"), Path("/bin/curl"))
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}$")
_STATUS_MARKER = b"\n__SAFE_CURL_STATUS__:"
_MINIMAL_ENV = {"LANG": "C", "LC_ALL": "C"}
_MAX_REQUEST_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class CurlPolicy:
    allowed_origins: tuple[str, ...]
    allowed_paths: tuple[str, ...] = ()
    max_response_bytes: int = 1024 * 1024
    connect_timeout_seconds: int = 10


@dataclass(frozen=True)
class CurlRequest:
    method: str
    url: str
    policy: CurlPolicy
    body: bytes = b""
    headers: tuple[tuple[str, str], ...] = ()
    timeout_seconds: int = 30


@dataclass(frozen=True)
class CurlResult:
    ok: bool
    status_code: int
    body: bytes
    error_code: str
    diagnostic: str
    blocked: bool = False


@dataclass(frozen=True)
class _ProcessOutput:
    returncode: int
    stdout: bytes
    timed_out: bool = False
    spawn_failed: bool = False


def _trusted_curl_from(candidates: tuple[Path, ...]) -> Path | None:
    """Return a fixed-path, root-owned, non-writable curl executable."""
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            info = resolved.stat()
        except OSError:
            continue
        safe_mode = not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        if (candidate.is_absolute() and stat.S_ISREG(info.st_mode)
                and info.st_uid == 0 and safe_mode and os.access(resolved, os.X_OK)):
            return resolved
    return None


def _curl_supports_response_bound(executable: Path) -> bool:
    try:
        result = subprocess.run(
            [str(executable), "--disable", "--version"], shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=dict(_MINIMAL_ENV), cwd="/", timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    first_line = (result.stdout or b"").decode("ascii", errors="ignore").splitlines()[:1]
    match = re.match(r"^curl (\d+)\.(\d+)\.(\d+)(?:\s|$)", first_line[0] if first_line else "")
    return bool(result.returncode == 0 and match and tuple(map(int, match.groups())) >= (8, 4, 0))


_DISCOVERED_CURL = _trusted_curl_from(_CURL_CANDIDATES)
_TRUSTED_CURL = (
    _DISCOVERED_CURL
    if _DISCOVERED_CURL is not None and _curl_supports_response_bound(_DISCOVERED_CURL)
    else None
)
_CURL_BLOCK_CODE = (
    "trusted_curl_unavailable" if _DISCOVERED_CURL is None else "curl_capability_unavailable"
)


def _failure(code: str, *, blocked: bool = False) -> CurlResult:
    messages = {
        "invalid_request": "request rejected by bounded transport policy",
        "invalid_url": "URL rejected by bounded transport policy",
        "invalid_header": "header rejected by bounded transport policy",
        "trusted_curl_unavailable": "trusted system curl is unavailable",
        "curl_capability_unavailable": "system curl lacks required response bounds",
        "unsupported_platform": "header file-descriptor transport is unsupported",
        "timeout": "bounded transport timed out",
        "response_too_large": "response exceeded the configured bound",
        "malformed_status": "transport returned malformed status evidence",
        "transport_unavailable": "provider transport is unavailable",
        "tls_verification_failed": "TLS verification failed",
        "transport_error": "bounded transport failed",
    }
    return CurlResult(False, 0, b"", code, messages[code], blocked)


def _origin_tuple(parsed: SplitResult) -> tuple[str, str, int | None] | None:
    try:
        port = parsed.port
    except ValueError:
        return None
    if parsed.username is not None or parsed.password is not None or not parsed.hostname:
        return None
    return parsed.scheme.lower(), parsed.hostname.lower(), port


def _valid_origin(origin: str) -> tuple[str, str, int | None] | None:
    parsed = urlsplit(origin)
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return None
    value = _origin_tuple(parsed)
    if value is None or value[0] not in {"http", "https"}:
        return None
    return value


def _validate_url(request: CurlRequest) -> SplitResult | None:
    if not isinstance(request.url, str) or not 1 <= len(request.url) <= 2048:
        return None
    if any(ord(char) < 0x21 or ord(char) > 0x7E for char in request.url):
        return None
    parsed = urlsplit(request.url)
    if parsed.query or parsed.fragment or not parsed.path.startswith("/"):
        return None
    origin = _origin_tuple(parsed)
    allowed = {_valid_origin(item) for item in request.policy.allowed_origins}
    if None in allowed or origin not in allowed:
        return None
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return None
    if request.policy.allowed_paths and parsed.path not in request.policy.allowed_paths:
        return None
    return parsed


def _header_payload(headers: tuple[tuple[str, str], ...]) -> bytes | None:
    lines: list[str] = []
    for item in headers:
        if not isinstance(item, tuple) or len(item) != 2:
            return None
        name, value = item
        if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
            return None
        if not isinstance(value, str) or not value or len(value) > 1024:
            return None
        if any(ord(char) < 0x20 or ord(char) > 0x7E for char in value):
            return None
        lines.append(f"{name}: {value}\n")
    payload = "".join(lines).encode("ascii")
    return payload if len(payload) <= 8192 else None


def _validate_request(request: CurlRequest) -> tuple[SplitResult, bytes] | CurlResult:
    if request.method not in {"GET", "POST"}:
        return _failure("invalid_request")
    if not isinstance(request.body, bytes) or len(request.body) > _MAX_REQUEST_BYTES:
        return _failure("invalid_request")
    policy = request.policy
    if (not isinstance(request.timeout_seconds, int) or not 1 <= request.timeout_seconds <= 3600
            or not isinstance(policy.connect_timeout_seconds, int)
            or not 1 <= policy.connect_timeout_seconds <= request.timeout_seconds
            or not isinstance(policy.max_response_bytes, int)
            or not 1 <= policy.max_response_bytes <= 16 * 1024 * 1024):
        return _failure("invalid_request")
    parsed = _validate_url(request)
    if parsed is None:
        return _failure("invalid_url")
    payload = _header_payload(request.headers)
    if payload is None:
        return _failure("invalid_header")
    return parsed, payload


def _command(request: CurlRequest, parsed: SplitResult, header_fd: int | None) -> list[str]:
    policy = request.policy
    command = [
        str(_TRUSTED_CURL), "--disable", "--silent", "--show-error",
        "--request", request.method,
        "--proto", f"={parsed.scheme}", "--proto-redir", f"={parsed.scheme}",
        "--max-redirs", "0", "--proxy", "", "--noproxy", "*",
        "--connect-timeout", str(policy.connect_timeout_seconds),
        "--max-time", str(request.timeout_seconds),
        "--max-filesize", str(policy.max_response_bytes),
    ]
    if header_fd is not None:
        command.extend(("--header", f"@/dev/fd/{header_fd}"))
    if request.method == "POST":
        command.extend(("--data-binary", "@-"))
    command.extend(("--write-out", _STATUS_MARKER.decode() + "%{http_code}", "--url", request.url))
    return command


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("header pipe closed")
        offset += written


def _close(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _close_process_streams(process: subprocess.Popen) -> None:
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(process, name, None)
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def _kill_and_drain(process: subprocess.Popen) -> bytes:
    try:
        process.kill()
    except OSError:
        pass
    try:
        stdout, _stderr = process.communicate(timeout=2)
        return stdout or b""
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass
        _close_process_streams(process)
        return b""


def _exchange(process: subprocess.Popen, body: bytes, timeout: int) -> _ProcessOutput:
    try:
        stdout, _stderr = process.communicate(input=body, timeout=timeout + 2)
        return _ProcessOutput(process.returncode, stdout or b"")
    except subprocess.TimeoutExpired:
        stdout = _kill_and_drain(process)
        return _ProcessOutput(process.returncode or 124, stdout or b"", timed_out=True)


def _abort_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    _kill_and_drain(process)


def _run(request: CurlRequest, parsed: SplitResult, header_payload: bytes) -> _ProcessOutput:
    read_fd = write_fd = None
    process = None
    try:
        if header_payload:
            read_fd, write_fd = os.pipe()
            os.set_inheritable(read_fd, False)
            os.set_inheritable(write_fd, False)
        command = _command(request, parsed, read_fd)
        process = subprocess.Popen(
            command, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, close_fds=True,
            pass_fds=(read_fd,) if read_fd is not None else (),
            env=dict(_MINIMAL_ENV), cwd="/",
        )
        _close(read_fd)
        read_fd = None
        if write_fd is not None:
            _write_all(write_fd, header_payload)
            _close(write_fd)
            write_fd = None
        return _exchange(process, request.body, request.timeout_seconds)
    except OSError:
        _abort_process(process)
        return _ProcessOutput(127, b"", spawn_failed=True)
    finally:
        _close(read_fd)
        _close(write_fd)


def _process_failure(output: _ProcessOutput) -> CurlResult | None:
    if output.timed_out or output.returncode == 28:
        return _failure("timeout")
    if output.spawn_failed or output.returncode in {6, 7}:
        return _failure("transport_unavailable")
    if output.returncode == 63:
        return _failure("response_too_large")
    if output.returncode in {35, 51, 58, 60, 77}:
        return _failure("tls_verification_failed")
    if output.returncode != 0:
        return _failure("transport_error")
    return None


def _parse_success(output: _ProcessOutput, maximum: int) -> CurlResult:
    try:
        body, raw_status = output.stdout.rsplit(_STATUS_MARKER, 1)
        status_text = raw_status.decode("ascii")
    except (ValueError, UnicodeError):
        return _failure("malformed_status")
    if len(status_text) != 3 or not status_text.isdigit():
        return _failure("malformed_status")
    if len(body) > maximum:
        return _failure("response_too_large")
    status = int(status_text)
    return CurlResult(200 <= status < 300, status, body, "", "")


def execute(request: CurlRequest) -> CurlResult:
    """Execute one bounded request without ambient config or credential argv."""
    if os.name != "posix" or not Path("/dev/fd").is_dir():
        return _failure("unsupported_platform", blocked=True)
    if _TRUSTED_CURL is None:
        return _failure(_CURL_BLOCK_CODE, blocked=True)
    validated = _validate_request(request)
    if isinstance(validated, CurlResult):
        return validated
    parsed, header_payload = validated
    output = _run(request, parsed, header_payload)
    failure = _process_failure(output)
    return failure or _parse_success(output, request.policy.max_response_bytes)
