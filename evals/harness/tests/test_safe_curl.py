#!/usr/bin/env python3
"""Security and lifecycle regressions for the bounded system-curl transport."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import safe_curl  # noqa: E402


FAKE_KEY = "AIza-SAFE-CURL-FAKE-KEY-DO-NOT-USE"
STATUS = b"\n__SAFE_CURL_STATUS__:200"


class _FakeProcess:
    def __init__(self, args, kwargs, stdout=b'{"ok":true}', returncode=0):
        self.args = args
        self.kwargs = kwargs
        self.stdout = stdout
        self.returncode = returncode
        self.killed = False
        passed = kwargs.get("pass_fds", ())
        self.header_fd = os.dup(passed[0]) if passed else None
        if self.header_fd is not None:
            os.set_blocking(self.header_fd, False)
        self.header_bytes = b""
        self.saw_header_eof = False
        self.input_bytes = None

    def _read_header(self):
        if self.header_fd is None:
            return
        while True:
            try:
                chunk = os.read(self.header_fd, 4096)
            except BlockingIOError:
                return
            if not chunk:
                self.saw_header_eof = True
                os.close(self.header_fd)
                self.header_fd = None
                return
            self.header_bytes += chunk

    def communicate(self, input=None, timeout=None):
        self._read_header()
        self.input_bytes = input
        return self.stdout + STATUS, b""

    def kill(self):
        self.killed = True


def _policy(max_bytes=4096):
    return safe_curl.CurlPolicy(
        allowed_origins=("https://example.test",),
        allowed_paths=("/v1/resource",),
        max_response_bytes=max_bytes,
        connect_timeout_seconds=2,
    )


def _request(headers=()):
    return safe_curl.CurlRequest(
        method="POST",
        url="https://example.test/v1/resource",
        policy=_policy(),
        body=b'{"hello":"world"}',
        headers=headers,
        timeout_seconds=5,
    )


def test_secret_exists_only_in_header_pipe(monkeypatch):
    captured = {}

    def fake_popen(args, **kwargs):
        captured["process"] = _FakeProcess(args, kwargs)
        return captured["process"]

    monkeypatch.setattr(safe_curl.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(safe_curl, "_TRUSTED_CURL", Path("/usr/bin/curl"))
    result = safe_curl.execute(_request((("x-goog-api-key", FAKE_KEY),)))

    proc = captured["process"]
    assert proc.args[1] == "--disable"
    assert FAKE_KEY not in repr(proc.args)
    assert FAKE_KEY not in repr(proc.kwargs)
    assert proc.kwargs["shell"] is False
    assert proc.kwargs["close_fds"] is True
    assert proc.kwargs["pass_fds"] and len(proc.kwargs["pass_fds"]) == 1
    assert proc.kwargs["env"] == {"LANG": "C", "LC_ALL": "C"}
    assert proc.header_bytes == f"x-goog-api-key: {FAKE_KEY}\n".encode()
    assert proc.saw_header_eof is True
    assert proc.input_bytes == b'{"hello":"world"}'
    assert result.ok is True and result.status_code == 200
    assert FAKE_KEY not in repr(result)


@pytest.mark.parametrize("value", ["bad\rkey", "bad\nkey", "bad\0key", "snowman-\N{SNOWMAN}"])
def test_header_controls_and_non_ascii_are_rejected_before_spawn(monkeypatch, value):
    called = False

    def fake_popen(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("must not spawn")

    monkeypatch.setattr(safe_curl.subprocess, "Popen", fake_popen)
    result = safe_curl.execute(_request((("x-goog-api-key", value),)))
    assert result.error_code == "invalid_header"
    assert called is False
    assert value not in result.diagnostic


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/v1/resource",
        "https://evil.test/v1/resource",
        "https://user@example.test/v1/resource",
        "https://example.test/v1/other",
        "https://example.test/v1/resource?key=secret",
        "https://example.test/v1/resource#fragment",
    ],
)
def test_url_must_match_exact_policy(monkeypatch, url):
    monkeypatch.setattr(safe_curl, "_TRUSTED_CURL", Path("/usr/bin/curl"))
    request = safe_curl.CurlRequest("GET", url, _policy(), timeout_seconds=5)
    result = safe_curl.execute(request)
    assert result.error_code == "invalid_url"


def test_arbitrary_http_is_rejected_even_if_caller_lists_it(monkeypatch):
    monkeypatch.setattr(safe_curl, "_TRUSTED_CURL", Path("/usr/bin/curl"))
    policy = safe_curl.CurlPolicy(("http://example.test",), ("/x",))
    result = safe_curl.execute(safe_curl.CurlRequest("GET", "http://example.test/x", policy))
    assert result.error_code == "invalid_url"


def test_response_limit_is_enforced_after_process(monkeypatch):
    def fake_popen(args, **kwargs):
        return _FakeProcess(args, kwargs, stdout=b"x" * 20)

    monkeypatch.setattr(safe_curl.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(safe_curl, "_TRUSTED_CURL", Path("/usr/bin/curl"))
    request = safe_curl.CurlRequest(
        "GET", "https://example.test/v1/resource", _policy(max_bytes=10), timeout_seconds=5,
    )
    result = safe_curl.execute(request)
    assert result.error_code == "response_too_large"
    assert result.body == b""


def test_timeout_kills_and_drains_child(monkeypatch):
    class TimeoutProcess(_FakeProcess):
        calls = 0

        def communicate(self, input=None, timeout=None):
            self._read_header()
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(self.args, timeout)
            return b"", b""

    captured = {}

    def fake_popen(args, **kwargs):
        captured["process"] = TimeoutProcess(args, kwargs)
        return captured["process"]

    monkeypatch.setattr(safe_curl.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(safe_curl, "_TRUSTED_CURL", Path("/usr/bin/curl"))
    result = safe_curl.execute(_request((("x-goog-api-key", FAKE_KEY),)))
    assert result.error_code == "timeout"
    assert captured["process"].killed is True
    assert captured["process"].calls == 2
    assert FAKE_KEY not in repr(result)


def test_second_timeout_kills_waits_and_closes_process_streams(monkeypatch):
    class Stream:
        closed = False

        def close(self):
            self.closed = True

    class TerminalTimeoutProcess:
        def __init__(self, args):
            self.args = args
            self.returncode = None
            self.calls = 0
            self.kills = 0
            self.waited = False
            self.stdin = Stream()
            self.stdout = Stream()
            self.stderr = Stream()

        def communicate(self, input=None, timeout=None):
            self.calls += 1
            raise subprocess.TimeoutExpired(self.args, timeout)

        def kill(self):
            self.kills += 1

        def wait(self, timeout=None):
            self.waited = True
            self.returncode = -9
            return -9

    captured = {}

    def fake_popen(args, **_kwargs):
        captured["process"] = TerminalTimeoutProcess(args)
        return captured["process"]

    monkeypatch.setattr(safe_curl.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(safe_curl, "_TRUSTED_CURL", Path("/usr/bin/curl"))
    result = safe_curl.execute(_request())
    process = captured["process"]
    assert result.error_code == "timeout"
    assert process.calls == 2 and process.kills == 2 and process.waited is True
    assert all(stream.closed for stream in (process.stdin, process.stdout, process.stderr))


def test_real_helper_reads_header_eof_before_stdin(monkeypatch, tmp_path):
    helper = tmp_path / "fd-eof-helper.py"
    helper.write_text(
        "import os, sys\n"
        "fd = int(sys.argv[1])\n"
        "header = b''\n"
        "while True:\n"
        "    chunk = os.read(fd, 4096)\n"
        "    if not chunk: break\n"
        "    header += chunk\n"
        "body = sys.stdin.buffer.read()\n"
        f"valid = header == b'x-goog-api-key: {FAKE_KEY}\\n' and body == b'{{\"hello\":\"world\"}}'\n"
        "if not valid: raise SystemExit(9)\n"
        "sys.stdout.buffer.write(b'{}\\n__SAFE_CURL_STATUS__:200')\n",
        encoding="utf-8",
    )

    def helper_command(_request, _parsed, header_fd):
        return [sys.executable, str(helper), str(header_fd)]

    monkeypatch.setattr(safe_curl, "_command", helper_command)
    monkeypatch.setattr(safe_curl, "_TRUSTED_CURL", Path(sys.executable))
    result = safe_curl.execute(_request((("x-goog-api-key", FAKE_KEY),)))
    assert result.ok is True and result.status_code == 200


def test_header_pipe_failure_kills_and_drains_spawned_child(monkeypatch):
    class BrokenPipeProcess:
        returncode = 1

        def __init__(self):
            self.killed = False
            self.drained = False

        def kill(self):
            self.killed = True

        def communicate(self, input=None, timeout=None):
            self.drained = True
            return b"", b""

    process = BrokenPipeProcess()
    monkeypatch.setattr(safe_curl.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(safe_curl, "_TRUSTED_CURL", Path("/usr/bin/curl"))
    result = safe_curl.execute(_request((("x-goog-api-key", FAKE_KEY),)))
    assert result.error_code == "transport_unavailable"
    assert process.killed is True
    assert process.drained is True


def test_repeated_header_requests_do_not_leak_parent_descriptors(monkeypatch):
    processes = []

    def fake_popen(args, **kwargs):
        process = _FakeProcess(args, kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(safe_curl.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(safe_curl, "_TRUSTED_CURL", Path("/usr/bin/curl"))
    before = len(os.listdir("/dev/fd"))
    for _index in range(25):
        assert safe_curl.execute(_request((("x-goog-api-key", FAKE_KEY),))).ok is True
    after = len(os.listdir("/dev/fd"))
    assert after == before
    assert all(process.header_fd is None for process in processes)


def test_untrusted_or_missing_curl_is_blocked(monkeypatch):
    monkeypatch.setattr(safe_curl, "_TRUSTED_CURL", None)
    monkeypatch.setattr(safe_curl, "_CURL_BLOCK_CODE", "trusted_curl_unavailable")
    result = safe_curl.execute(_request())
    assert result.error_code == "trusted_curl_unavailable"
    assert result.blocked is True


@pytest.mark.parametrize(
    ("version_output", "supported"),
    [(b"curl 8.3.0 (test)\n", False), (b"curl 8.4.0 (test)\n", True),
     (b"curl 9.0.0 (test)\n", True), (b"not curl\n", False)],
)
def test_curl_response_bound_requires_version_8_4(monkeypatch, version_output, supported):
    captured = {}

    def fake_run(args, **kwargs):
        from types import SimpleNamespace

        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=version_output)

    monkeypatch.setattr(safe_curl.subprocess, "run", fake_run)
    assert safe_curl._curl_supports_response_bound(Path("/usr/bin/curl")) is supported
    assert captured["args"][1] == "--disable"
    assert captured["kwargs"]["env"] == {"LANG": "C", "LC_ALL": "C"}


def test_old_curl_capability_is_blocked_before_request(monkeypatch):
    monkeypatch.setattr(safe_curl, "_TRUSTED_CURL", None)
    monkeypatch.setattr(safe_curl, "_CURL_BLOCK_CODE", "curl_capability_unavailable")
    result = safe_curl.execute(_request())
    assert result.error_code == "curl_capability_unavailable"
    assert result.blocked is True


class _DelayedHandler(BaseHTTPRequestHandler):
    entered = threading.Event()
    release = threading.Event()
    observed_key = None

    def do_GET(self):  # noqa: N802
        type(self).observed_key = self.headers.get("x-goog-api-key")
        type(self).entered.set()
        type(self).release.wait(timeout=5)
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def _local_request(port, key=FAKE_KEY):
    policy = safe_curl.CurlPolicy(
        (f"http://127.0.0.1:{port}",), ("/wait",), connect_timeout_seconds=2,
    )
    return safe_curl.CurlRequest(
        "GET", f"http://127.0.0.1:{port}/wait", policy,
        headers=(("x-goog-api-key", key),), timeout_seconds=5,
    )


def test_real_process_listing_and_ambient_config_do_not_expose_key(monkeypatch, tmp_path):
    if safe_curl._TRUSTED_CURL is None:
        pytest.skip("trusted system curl unavailable")
    marker = tmp_path / "shadow-ran"
    trace = tmp_path / "curl-trace"
    shadow = tmp_path / "curl"
    shadow.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 91\n", encoding="utf-8")
    shadow.chmod(0o755)
    (tmp_path / ".curlrc").write_text(f"--insecure\n--trace-ascii '{trace}'\n", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("CURL_CA_BUNDLE", str(tmp_path / "bad-ca"))

    server = ThreadingHTTPServer(("127.0.0.1", 0), _DelayedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    result_box = {}
    request_thread = threading.Thread(
        target=lambda: result_box.setdefault("result", safe_curl.execute(_local_request(server.server_port))),
        daemon=True,
    )
    request_thread.start()
    assert _DelayedHandler.entered.wait(timeout=5)
    process_text = subprocess.run(
        ["/bin/ps", "-axo", "command"], capture_output=True, text=True, check=True,
    ).stdout
    _DelayedHandler.release.set()
    request_thread.join(timeout=8)
    server.shutdown()
    server.server_close()

    assert FAKE_KEY not in process_text
    assert result_box["result"].ok is True
    assert _DelayedHandler.observed_key == FAKE_KEY
    assert not marker.exists()
    assert not trace.exists()
