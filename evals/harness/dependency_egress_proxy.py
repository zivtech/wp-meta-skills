"""Reviewed lock validation and bounded HTTPS CONNECT forwarding."""
from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
import os
import re
import selectors
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

NPM_HOSTS = frozenset({"registry.npmjs.org"})
COMPOSER_HOSTS = frozenset({"api.github.com", "codeload.github.com"})
HEADER_LIMIT = 8192
RESOLVER_OUTPUT_LIMIT = 8192
RESOLVER_HELPER = """import json,socket,sys
try:
    answer=socket.getaddrinfo(sys.argv[1],443,type=socket.SOCK_STREAM)
    if not 1<=len(answer)<=64: raise OverflowError()
    value={"records":[[int(f),int(s),int(p),list(a)] for f,s,p,_c,a in answer]}
except BaseException as exc:
    value={"error":type(exc).__name__}
sys.stdout.write(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)+"\\n")
"""


@dataclass(frozen=True)
class AcquisitionProfile:
    kind: str
    manifest_path: str
    lock_path: str
    manifest_sha256: str
    lock_sha256: str
    allowed_hosts: frozenset[str]
    image_key: str
    versions: tuple[str, ...]
    amd64_digest: str
    arm64_digest: str


ACQUISITION_PROFILES = MappingProxyType(
    {
        "block-scripts-32.4.1-smoke": AcquisitionProfile("npm", "package.json", "package-lock.json", "e2259282345ac90cb5645507efd0daba536b2742be3eab676db10fd7fc1fb4f6", "990d9a67783977a5a4c54035666ebc48f7aaac8cdf69f2313caf2a17b317fa33", NPM_HOSTS, "node", ("22.23.1", "10.9.8"), "sha256:a149cd71dccd68704a07d4e4ca3e610c27301852b0f556865cfdb6e2856f8bed", "sha256:6db9be2ebb4bafb687a078ef5ba1b1dd256e8004d246a31fd210b6b848ab6be2"),
        "block-interactivity-6.48.1": AcquisitionProfile("npm", "package.json", "package-lock.json", "71b29ec85d0ccffab3ef9d10616eb3ab61829546981e24a5ab17a844c8528c97", "53f635a658e1e4504ec41a5c405aa3230566ecbd529f1d137b41c13b30ffc4cc", NPM_HOSTS, "node", ("22.23.1", "10.9.8"), "sha256:a149cd71dccd68704a07d4e4ca3e610c27301852b0f556865cfdb6e2856f8bed", "sha256:6db9be2ebb4bafb687a078ef5ba1b1dd256e8004d246a31fd210b6b848ab6be2"),
        "block-scripts-32.4.1-deprecation": AcquisitionProfile("npm", "package.json", "package-lock.json", "157195077dc1169f556b3f193fa597e5d4f1c0fa33c5d41e37a389136ba973a3", "66a25aaf8dd6545320c35fb2efa525a473e5bf7fde8a1f496feb726de93d3812", NPM_HOSTS, "node", ("22.23.1", "10.9.8"), "sha256:a149cd71dccd68704a07d4e4ca3e610c27301852b0f556865cfdb6e2856f8bed", "sha256:6db9be2ebb4bafb687a078ef5ba1b1dd256e8004d246a31fd210b6b848ab6be2"),
        "plugin-phpunit-12.5.31": AcquisitionProfile("composer", "composer.json", "composer.lock", "5d3a497a4e9a581a7c39fff1152ba9f6423fc1c89c8a8836d32338d3a12ddec2", "47eee06cd2f4990a5660ea35f54d8d0c161fe8e3e304debf6b267dde10548b42", COMPOSER_HOSTS, "composer", ("2.8.12", "8.4.14"), "sha256:0d264a0f1e5be23ba363447768df7b30c33d542711ea12e37770ed7b13bf4eaa", "sha256:cc2fd435c5dd57485421bc19c3e9226c29417f8065c00dcef2b2e361090f3c2f"),
    }
)


@dataclass(frozen=True)
class ProxyLimits:
    connections: int = 8
    direction_bytes: int = 128 * 1024 * 1024
    tunnel_bytes: int = 256 * 1024 * 1024
    acquisition_bytes: int = 256 * 1024 * 1024
    duration: int = 300
    idle: int = 60
    dns_timeout: int = 5


class AcquisitionByteBudget:
    """One conservative payload budget shared by every acquisition tunnel."""

    def __init__(self, limit):
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("acquisition byte budget must be a positive integer")
        self.limit = limit
        self.used = 0
        self.lock = threading.Lock()

    def charge(self, amount):
        if not isinstance(amount, int) or amount < 0:
            raise ValueError("acquisition byte charge must be a nonnegative integer")
        with self.lock:
            if self.used + amount > self.limit:
                raise ValueError("acquisition-wide byte limit exceeded")
            self.used += amount


def _https_host(url, allowed):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("dependency URL must be credential-free HTTPS port 443")
    if parsed.hostname not in allowed:
        raise ValueError(f"dependency host is not allowed: {parsed.hostname}")
    return parsed.hostname


def _reject_npm_spec(value):
    if not isinstance(value, str) or value.startswith(("file:", "link:", "git", "http:", "https:", "npm:")):
        raise ValueError("npm dependency spec is local, remote, aliased, or malformed")


def validate_npm_lock(data):
    if data.get("lockfileVersion") != 3 or not isinstance(data.get("packages"), dict):
        raise ValueError("npm lock is missing or unsupported")
    for path, package in data["packages"].items():
        if path == "":
            continue
        if package.get("link") or package.get("bundled") or package.get("inBundle"):
            raise ValueError("npm linked or bundled packages are forbidden")
        resolved, integrity = package.get("resolved"), package.get("integrity")
        if not isinstance(resolved, str) or not isinstance(integrity, str) or not integrity.startswith("sha512-"):
            raise ValueError(f"npm package lacks reviewed resolution/integrity: {path}")
        try:
            decoded = base64.b64decode(integrity[7:], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("npm integrity is not canonical base64 sha512") from exc
        if len(decoded) != 64:
            raise ValueError("npm integrity is not sha512 length")
        _https_host(resolved, NPM_HOSTS)
    return NPM_HOSTS


def validate_npm_manifest(lock, manifest):
    validate_npm_lock(lock)
    root = lock["packages"].get("", {})
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        declared = manifest.get(key, {})
        if not isinstance(declared, dict) or root.get(key, {}) != declared:
            raise ValueError(f"npm root manifest mismatch: {key}")
        for value in declared.values():
            _reject_npm_spec(value)
    if manifest.get("publishConfig", {}).get("registry"):
        raise ValueError("custom npm registry is forbidden")
    return NPM_HOSTS


def validate_composer_lock(lock, manifest):
    config = manifest.get("config", {})
    if set(config) - {"platform", "allow-plugins"} or manifest.get("repositories") or manifest.get("scripts"):
        raise ValueError("Composer manifest enables repository, script, credential, or plugin behavior")
    if config.get("allow-plugins") not in {False, None}:
        raise ValueError("Composer plugins must be disabled")
    packages = lock.get("packages", []) + lock.get("packages-dev", [])
    if not packages or not re.fullmatch(r"[0-9a-f]{32}", lock.get("content-hash", "")):
        raise ValueError("Composer lock is empty or lacks content hash")
    for package in packages:
        dist = package.get("dist", {})
        if dist.get("type") != "zip" or not re.fullmatch(r"[0-9a-f]{40}", dist.get("reference", "")):
            raise ValueError("Composer package requires immutable ZIP dist")
        _https_host(dist.get("url", ""), COMPOSER_HOSTS)
        if package.get("type") != "library":
            raise ValueError("only Composer library packages are allowed")
    return COMPOSER_HOSTS


def validate_lock_bytes(kind, lock_bytes, manifest_bytes):
    lock = _strict_json_bytes(lock_bytes)
    manifest = _strict_json_bytes(manifest_bytes)
    return validate_npm_manifest(lock, manifest) if kind == "npm" else validate_composer_lock(lock, manifest)


def _strict_json_bytes(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f"nonfinite JSON value: {value}")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=reject_constant)


def validate_ip(address):
    ip = ipaddress.ip_address(address)
    denied = (not ip.is_global, ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified)
    if any(denied):
        raise ValueError(f"resolved address is forbidden: {ip}")
    return str(ip)


def _validate_transition_ip(address):
    ip = ipaddress.ip_address(address)
    translated = ip in ipaddress.ip_network("64:ff9b::/96") or ip in ipaddress.ip_network("64:ff9b:1::/48")
    if isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour or ip.teredo or translated):
        raise ValueError("IPv6 transition address is forbidden")
    return validate_ip(address)


def validate_listener_ip(address):
    ip = ipaddress.ip_address(address)
    if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        raise ValueError("proxy listener must be an exact private non-loopback IPv4 address")
    return str(ip)


def _resolver_record(value):
    if type(value) is not list or len(value) != 4:
        raise ValueError("resolver record shape drift")
    family,socktype,proto,address=value
    integers=(family,socktype,proto)
    if any(type(item) is not int for item in integers):
        raise ValueError("resolver record type drift")
    if family not in {socket.AF_INET,socket.AF_INET6} or socktype != socket.SOCK_STREAM or proto != socket.IPPROTO_TCP:
        raise ValueError("resolver socket profile drift")
    expected=2 if family==socket.AF_INET else 4
    if type(address) is not list or len(address)!=expected or type(address[0]) is not str or address[1]!=443:
        raise ValueError("resolver socket address drift")
    if family==socket.AF_INET6 and (type(address[2]) is not int or type(address[3]) is not int or address[2:]!=[0,0]):
        raise ValueError("resolver IPv6 scope drift")
    return family,socktype,proto,"",tuple(address)


def _decode_resolver_output(payload):
    if not isinstance(payload,bytes) or len(payload)>RESOLVER_OUTPUT_LIMIT or not payload.endswith(b"\n") or payload.count(b"\n")!=1:
        raise RuntimeError("resolver output framing drift")
    value=_strict_json_bytes(payload)
    canonical=(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
    if payload!=canonical or type(value) is not dict:
        raise RuntimeError("resolver output canonical encoding drift")
    if set(value)=={"error"} and isinstance(value["error"],str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}",value["error"]):
        raise ValueError(f"CONNECT DNS resolution failed: {value['error']}")
    if set(value)!={"records"} or type(value["records"]) is not list or not 1<=len(value["records"])<=64:
        raise ValueError("resolver output schema drift")
    return tuple(_resolver_record(item) for item in value["records"])


def _kill_and_reap_resolver(process):
    try: os.killpg(process.pid,signal.SIGKILL)
    except ProcessLookupError: pass
    try: process.communicate(timeout=1)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("DNS resolver process group survived forced termination") from exc
    if process.returncode is None:
        raise RuntimeError("DNS resolver process was not reaped")


def resolve_public_records(host, timeout=5):
    if host not in NPM_HOSTS|COMPOSER_HOSTS:
        raise ValueError("CONNECT DNS host is not reviewed")
    command=[sys.executable,"-I","-S","-B","-c",RESOLVER_HELPER,host]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env={"PATH":"/usr/local/bin:/usr/bin:/bin"},start_new_session=True)
    try: payload,_stderr=process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_and_reap_resolver(process)
        raise TimeoutError("CONNECT DNS resolution timed out") from exc
    if process.returncode:
        raise ValueError("CONNECT DNS resolver exited nonzero")
    return _validate_records(_decode_resolver_output(payload))


def _validate_records(answer):
    records = []
    for family, socktype, proto, _canonname, sockaddr in answer:
        _validate_transition_ip(sockaddr[0])
        record = (family, socktype, proto, sockaddr)
        if record not in records:
            records.append(record)
    if not records:
        raise ValueError("CONNECT host has no public address")
    return tuple(records)


def parse_connect(request, allowed):
    if len(request) > HEADER_LIMIT or not request.endswith(b"\r\n\r\n"):
        raise ValueError("CONNECT headers are incomplete or oversized")
    if any((byte < 32 and byte not in {10, 13}) or byte == 127 for byte in request) or b"\r\n " in request or b"\r\n\t" in request:
        raise ValueError("CONNECT headers contain control or obs-fold")
    lines = request[:-4].split(b"\r\n")
    matched = re.fullmatch(rb"CONNECT ([a-z0-9.-]+):443 HTTP/1\.1", lines[0])
    if not matched:
        raise ValueError("CONNECT request line is noncanonical")
    host = matched.group(1).decode("ascii")
    if host not in allowed:
        raise ValueError("CONNECT authority is not allowed")
    headers = {}
    pattern = re.compile(rb"([!#$%&'*+\-.^_`|~0-9A-Za-z]+): ([\x20-\x7e]*)")
    for raw in lines[1:]:
        header = pattern.fullmatch(raw)
        if not header:
            raise ValueError("CONNECT header is noncanonical")
        name = header.group(1).decode("ascii").casefold()
        if name in headers or name in {"proxy-authorization", "content-length", "transfer-encoding"}:
            raise ValueError("CONNECT header is duplicate or forbidden")
        headers[name] = header.group(2).decode("ascii")
    if len(headers) > 32 or headers.get("host") != f"{host}:443":
        raise ValueError("CONNECT Host header is missing or mismatched")
    return host


def _read_connect_header(client, timeout=10):
    data = bytearray()
    deadline = time.monotonic() + timeout
    while b"\r\n\r\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("CONNECT header deadline exceeded")
        client.settimeout(remaining)
        chunk = client.recv(min(1024, HEADER_LIMIT + 1 - len(data)))
        if not chunk:
            raise ValueError("CONNECT headers are incomplete")
        data.extend(chunk)
        if len(data) > HEADER_LIMIT:
            raise ValueError("CONNECT headers are oversized")
    end = data.index(b"\r\n\r\n") + 4
    return bytes(data[:end]), bytes(data[end:])


def _relay(client, upstream, limits, budget, initial_client_bytes=0):
    selector = selectors.DefaultSelector()
    selector.register(client, selectors.EVENT_READ, (upstream, "client"))
    selector.register(upstream, selectors.EVENT_READ, (client, "upstream"))
    counts = {"client": initial_client_bytes, "upstream": 0}
    started = last_activity = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            if now - started >= limits.duration:
                raise TimeoutError("CONNECT tunnel duration exceeded")
            if now - last_activity >= limits.idle:
                raise TimeoutError("CONNECT tunnel idle limit exceeded")
            wait = min(1, limits.duration - (now - started), limits.idle - (now - last_activity))
            for key, _mask in selector.select(max(0, wait)):
                target, direction = key.data
                chunk = key.fileobj.recv(65536)
                if not chunk:
                    return counts
                counts[direction] += len(chunk)
                if counts[direction] > limits.direction_bytes or sum(counts.values()) > limits.tunnel_bytes:
                    raise ValueError("CONNECT tunnel byte limit exceeded")
                budget.charge(len(chunk))
                remaining = limits.duration - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("CONNECT tunnel duration exceeded")
                target.settimeout(max(0.001, min(limits.idle, remaining)))
                target.sendall(chunk)
                last_activity = time.monotonic()
    finally:
        selector.close()


def _connect_record(record):
    family, socktype, proto, sockaddr = record
    upstream = socket.socket(family, socktype, proto)
    upstream.settimeout(10)
    try:
        upstream.connect(sockaddr)
    except BaseException:
        upstream.close()
        raise
    return upstream


def _handle_connect_core(client, allowed, limits, budget, resolver, connector):
    request, residue = _read_connect_header(client)
    host = parse_connect(request, allowed)
    records = resolver(host)
    upstream = connector(records[0])
    try:
        if len(residue) > limits.direction_bytes or len(residue) > limits.tunnel_bytes:
            raise ValueError("CONNECT tunnel byte limit exceeded")
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        if residue:
            budget.charge(len(residue))
            upstream.sendall(residue)
        return _relay(client, upstream, limits, budget, len(residue))
    finally:
        upstream.close()
        client.close()


def handle_connect(client, allowed, limits, budget):
    return _handle_connect_core(client, allowed, limits, budget, lambda host: resolve_public_records(host, limits.dns_timeout), _connect_record)


class ProxyStatus:
    def __init__(self, path, nonce):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.data = {"nonce": nonce, "accepted": 0, "active": 0, "completed": 0, "rejected": 0, "client_bytes": 0, "upstream_bytes": 0}
        self._write()

    def _write(self):
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or (info.st_uid, info.st_gid) != (os.getuid(), os.getgid()):
                raise RuntimeError("proxy status file identity drift")
            payload = json.dumps(self.data, separators=(",", ":"), sort_keys=True) + "\n"
            _write_all(descriptor, payload.encode("utf-8")); os.fsync(descriptor)
        except Exception:
            try: temporary.unlink()
            except OSError: pass
            raise
        finally:
            os.close(descriptor)
        os.replace(temporary, self.path)

    def update(self, **changes):
        with self.lock:
            self.data = {**self.data, **{key: self.data[key] + value for key, value in changes.items()}}
            self._write()

    def finalize(self):
        with self.lock:
            self._write()


def serve(host, port, peer, allowed, limits, status):
    listener = socket.create_server((host, port))
    listener.settimeout(1)
    semaphore = threading.BoundedSemaphore(limits.connections)
    stopping = threading.Event()
    workers = set()
    workers_lock = threading.Lock()
    budget = AcquisitionByteBudget(limits.acquisition_bytes)
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stopping.set())
    while not stopping.is_set():
        try:
            client, address = listener.accept()
        except TimeoutError:
            continue
        if address[0] != peer or not semaphore.acquire(False):
            client.close()
            status.update(rejected=1)
            continue
        status.update(accepted=1, active=1)

        def run(sock=client):
            try:
                counts = handle_connect(sock, allowed, limits, budget)
                status.update(completed=1, client_bytes=counts["client"], upstream_bytes=counts["upstream"])
            except BaseException:
                sock.close()
                status.update(rejected=1)
            finally:
                status.update(active=-1)
                semaphore.release()
                with workers_lock:
                    workers.discard(threading.current_thread())

        worker = threading.Thread(target=run)
        with workers_lock:
            workers.add(worker)
        worker.start()
    listener.close()
    deadline = time.monotonic() + limits.idle + 1
    with workers_lock:
        remaining = tuple(workers)
    for worker in remaining:
        worker.join(max(0, deadline - time.monotonic()))
    if any(worker.is_alive() for worker in remaining):
        raise RuntimeError("proxy workers did not stop")
    status.finalize()


def _write_all(descriptor, payload):
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short proxy control-file write")
        view = view[written:]


def _write_pid_file(path, nonce):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600); info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or (info.st_uid, info.st_gid) != (os.getuid(), os.getgid()):
            raise RuntimeError("proxy PID file identity drift")
        payload = json.dumps({"nonce": nonce, "pid": os.getpid()}, separators=(",", ":"), sort_keys=True) + "\n"
        _write_all(descriptor, payload.encode("ascii")); os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", required=True)
    parser.add_argument("--peer", required=True)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--hosts", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--pid-file", required=True)
    parser.add_argument("--nonce", required=True)
    args = parser.parse_args()
    allowed = frozenset(args.hosts.split(","))
    if not allowed or not allowed <= (NPM_HOSTS | COMPOSER_HOSTS):
        raise SystemExit("invalid proxy host allowlist")
    validate_listener_ip(args.listen)
    validate_listener_ip(args.peer)
    _write_pid_file(args.pid_file, args.nonce)
    serve(args.listen, args.port, args.peer, allowed, ProxyLimits(), ProxyStatus(args.status, args.nonce))


if __name__ == "__main__":
    main()
