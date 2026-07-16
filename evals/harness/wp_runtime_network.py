"""Host-listener evidence helpers for the isolated WordPress runtime."""
from __future__ import annotations

import contextlib
import ipaddress
import socket


def _host_listener_address():
    probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1",9))
        address=probe.getsockname()[0]
    finally:
        probe.close()
    parsed=ipaddress.ip_address(address)
    if (not isinstance(parsed,ipaddress.IPv4Address) or parsed.is_loopback
            or parsed.is_link_local or parsed.is_multicast or parsed.is_unspecified):
        raise RuntimeError("controlled host listener address is unavailable")
    return address


@contextlib.contextmanager
def controlled_host_listener():
    address=_host_listener_address()
    server=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    server.bind((address,0)); server.listen(8)
    try:
        yield server,address,server.getsockname()[1]
    finally:
        server.close()


def assert_listener_unreached(server):
    server.setblocking(False)
    try: connection,_address=server.accept()
    except BlockingIOError: return
    connection.close()
    raise RuntimeError("controlled host listener was reachable")
