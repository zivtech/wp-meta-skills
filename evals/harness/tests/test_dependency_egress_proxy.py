import errno, json, os, signal, socket, stat, subprocess, sys, threading, time
from pathlib import Path
import pytest
HARNESS=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(HARNESS))
import dependency_egress_proxy as proxy

def test_production_limits_preserve_concurrency_duration_and_bounded_idle():
    limits=proxy.ProxyLimits()
    assert (limits.connections,limits.duration,limits.idle)==(8,300,10)

def test_actual_reviewed_locks_validate():
    locks=HARNESS/"approved-locks"
    for name in ("block-scripts-32.4.1-smoke.package-lock.json","block-interactivity-6.48.1.package-lock.json","block-scripts-32.4.1-deprecation.package-lock.json"):
        assert proxy.validate_npm_lock(json.loads((locks/name).read_text()))==proxy.NPM_HOSTS
    composer=json.loads((locks/"plugin-phpunit-12.5.31.composer.lock").read_text())
    manifest={"config":{"allow-plugins":False}}
    assert proxy.validate_composer_lock(composer,manifest)==proxy.COMPOSER_HOSTS

@pytest.mark.parametrize("resolved",["http://registry.npmjs.org/a.tgz","file:../a","git+https://github.com/a/b","https://user:pass@registry.npmjs.org/a","https://evil.example/a"])
def test_npm_rejects_unsafe_sources(resolved):
    lock={"lockfileVersion":3,"packages":{"":{"name":"x"},"node_modules/x":{"version":"1","resolved":resolved,"integrity":"sha512-good"}}}
    with pytest.raises(ValueError): proxy.validate_npm_lock(lock)

def test_npm_requires_integrity_and_composer_rejects_active_metadata():
    lock={"lockfileVersion":3,"packages":{"":{},"node_modules/x":{"resolved":"https://registry.npmjs.org/x/-/x.tgz"}}}
    with pytest.raises(ValueError,match="integrity"): proxy.validate_npm_lock(lock)
    package={"name":"x/y","type":"composer-plugin","dist":{"type":"zip","url":"https://api.github.com/repos/x/y/zipball/a","reference":"a"}}
    with pytest.raises(ValueError): proxy.validate_composer_lock({"packages":[package]},{"repositories":[{"type":"vcs"}]})

def test_npm_rejects_links_root_manifest_drift_and_custom_registry():
    integrity="sha512-"+__import__("base64").b64encode(b"x"*64).decode()
    lock={"lockfileVersion":3,"packages":{"":{"dependencies":{"x":"1.0.0"}},"node_modules/x":{"link":True,"resolved":"https://registry.npmjs.org/x/-/x.tgz","integrity":integrity}}}
    with pytest.raises(ValueError,match="linked"): proxy.validate_npm_lock(lock)
    lock["packages"]["node_modules/x"].pop("link")
    with pytest.raises(ValueError,match="manifest mismatch"): proxy.validate_npm_manifest(lock,{"dependencies":{"x":"2.0.0"}})
    with pytest.raises(ValueError,match="custom npm registry"): proxy.validate_npm_manifest(lock,{"dependencies":{"x":"1.0.0"},"publishConfig":{"registry":"https://evil"}})

@pytest.mark.parametrize("address",["127.0.0.1","10.0.0.1","172.17.0.1","192.168.1.1","169.254.169.254","::1","fe80::1","0.0.0.0","224.0.0.1"])
def test_private_metadata_gateway_and_local_addresses_rejected(address):
    with pytest.raises(ValueError,match="forbidden"): proxy.validate_ip(address)

def test_connect_parser_is_exact_host_port_and_method():
    valid=b"CONNECT registry.npmjs.org:443 HTTP/1.1\r\nHost: registry.npmjs.org:443\r\n\r\n"
    assert proxy.parse_connect(valid,proxy.NPM_HOSTS)=="registry.npmjs.org"
    for request in (b"GET https://registry.npmjs.org HTTP/1.1\r\n",b"CONNECT registry.npmjs.org:80 HTTP/1.1\r\n",b"CONNECT evil.example:443 HTTP/1.1\r\n"):
        with pytest.raises(ValueError): proxy.parse_connect(request,proxy.NPM_HOSTS)
    with pytest.raises(ValueError,match="forbidden"): proxy.parse_connect(b"CONNECT registry.npmjs.org:443 HTTP/1.1\r\nHost: registry.npmjs.org:443\r\nProxy-Authorization: Basic abc\r\n\r\n",proxy.NPM_HOSTS)
    with pytest.raises(ValueError,match="incomplete"): proxy.parse_connect(b"CONNECT registry.npmjs.org:443 HTTP/1.1\r\n",proxy.NPM_HOSTS)

def test_fake_allowed_registry_tunnel_resolves_once_and_connects_numeric_record():
    listener=socket.create_server(("127.0.0.1",0)); port=listener.getsockname()[1]
    record=(socket.AF_INET,socket.SOCK_STREAM,6,("93.184.216.34",443)); resolved=[]; received=[]
    def resolver(host):
        resolved.append(host); return (record,)
    def connector(item):
        received.append(item); return socket.create_connection(("127.0.0.1",port),timeout=2)
    client,server=socket.socketpair()
    limits=proxy.ProxyLimits(duration=2)
    args=(server,proxy.NPM_HOSTS,limits,proxy.AcquisitionByteBudget(limits.acquisition_bytes),resolver,connector)
    thread=threading.Thread(target=proxy._handle_connect_core,args=args,daemon=True); thread.start()
    client.sendall(b"CONNECT registry.npmjs.org:443 HTTP/1.1\r\nHost: registry.npmjs.org:443\r\n\r\n"); upstream,_=listener.accept()
    assert resolved==["registry.npmjs.org"] and received==[record]
    assert b"200 Connection Established" in client.recv(1024)
    client.sendall(b"ping"); assert upstream.recv(4)==b"ping"
    upstream.sendall(b"pong"); assert client.recv(4)==b"pong"
    client.close(); upstream.close(); listener.close(); thread.join(2)

def test_production_connector_cannot_perform_second_hostname_resolution():
    source=__import__("inspect").getsource(proxy._connect_record)
    assert "getaddrinfo" not in source and "gethost" not in source
    assert "upstream.connect(sockaddr)" in source

def test_redirect_requires_a_new_allowed_connect():
    with pytest.raises(ValueError): proxy.parse_connect(b"CONNECT redirect.evil:443 HTTP/1.1\r\nHost: redirect.evil:443\r\n\r\n",proxy.COMPOSER_HOSTS)

def test_fragmented_header_preserves_tls_residue():
    client,server=socket.socketpair(); request=b"CONNECT registry.npmjs.org:443 HTTP/1.1\r\nHost: registry.npmjs.org:443\r\n\r\nTLS"
    client.sendall(request[:17]); client.sendall(request[17:])
    header,residue=proxy._read_connect_header(server)
    assert header.endswith(b"\r\n\r\n") and residue==b"TLS"
    client.close(); server.close()

@pytest.mark.parametrize("payload",[
 b"CONNECT registry.npmjs.org:443 HTTP/1.0\r\nHost: registry.npmjs.org:443\r\n\r\n",
 b"CONNECT  registry.npmjs.org:443 HTTP/1.1\r\nHost: registry.npmjs.org:443\r\n\r\n",
 b"CONNECT registry.npmjs.org:443 HTTP/1.1\r\nhost: registry.npmjs.org:443\r\nHOST: registry.npmjs.org:443\r\n\r\n",
 b"CONNECT registry.npmjs.org:443 HTTP/1.1\r\nHost:\tregistry.npmjs.org:443\r\n\r\n",
])
def test_connect_rejects_noncanonical_or_duplicate_headers(payload):
    with pytest.raises(ValueError): proxy.parse_connect(payload,proxy.NPM_HOSTS)

@pytest.mark.parametrize("address",["::ffff:93.184.216.34","64:ff9b::5db8:d822","64:ff9b:1:2::5db8:d822","2002:5db8:d822::","2001:0000:4136:e378:8000:63bf:3fff:fdd2"])
def test_transition_addresses_are_rejected(address):
    with pytest.raises(ValueError,match="transition"): proxy._validate_transition_ip(address)

def test_proxy_listener_requires_private_nonloopback_ipv4():
    assert proxy.validate_listener_ip("172.28.0.3")=="172.28.0.3"
    for address in ("127.0.0.1","169.254.1.1","93.184.216.34","fd00::3"):
        with pytest.raises(ValueError,match="private non-loopback"): proxy.validate_listener_ip(address)

def test_mixed_public_private_dns_answer_is_rejected_before_connect():
    answer=[(socket.AF_INET,socket.SOCK_STREAM,6,"",("93.184.216.34",443)),(socket.AF_INET,socket.SOCK_STREAM,6,"",("169.254.169.254",443))]
    with pytest.raises(ValueError,match="forbidden"): proxy._validate_records(answer)

@pytest.mark.parametrize("header",[b"Content-Length: 1",b"Transfer-Encoding: chunked",b"X-Bad: value\x7f"])
def test_connect_rejects_framing_and_del_controls(header):
    payload=b"CONNECT registry.npmjs.org:443 HTTP/1.1\r\nHost: registry.npmjs.org:443\r\n"+header+b"\r\n\r\n"
    with pytest.raises(ValueError): proxy.parse_connect(payload,proxy.NPM_HOSTS)

def test_lock_byte_helper_rejects_duplicate_and_nonfinite_json():
    for lock in (b'{"lockfileVersion":3,"lockfileVersion":3,"packages":{}}',b'{"lockfileVersion":NaN,"packages":{}}'):
        with pytest.raises(ValueError): proxy.validate_lock_bytes("npm",lock,b"{}")

def test_relay_enforces_independent_direction_and_idle_limits():
    client,client_peer=socket.socketpair(); upstream,upstream_peer=socket.socketpair(); errors=[]
    limits=proxy.ProxyLimits(direction_bytes=3,tunnel_bytes=20,duration=2,idle=1)
    budget=proxy.AcquisitionByteBudget(20)
    thread=threading.Thread(target=lambda:_capture_error(errors,proxy._relay,client,upstream,limits,budget),daemon=True); thread.start()
    client_peer.sendall(b"four"); thread.join(2)
    assert errors and "byte limit" in str(errors[0])
    for item in (client,client_peer,upstream,upstream_peer): item.close()
    client,client_peer=socket.socketpair(); upstream,upstream_peer=socket.socketpair(); errors=[]
    idle=proxy.ProxyLimits(direction_bytes=10,tunnel_bytes=20,duration=2,idle=0.05)
    budget=proxy.AcquisitionByteBudget(20)
    thread=threading.Thread(target=lambda:_capture_error(errors,proxy._relay,client,upstream,idle,budget),daemon=True); thread.start(); thread.join(1)
    assert errors and "idle" in str(errors[0])
    for item in (client,client_peer,upstream,upstream_peer): item.close()

def _relay_fixture(limits=None,budget=None):
    client,client_peer=socket.socketpair(); upstream,upstream_peer=socket.socketpair(); errors=[]; results=[]
    client_peer.settimeout(2); upstream_peer.settimeout(2)
    limits=limits or proxy.ProxyLimits(duration=2,idle=1)
    budget=budget or proxy.AcquisitionByteBudget(limits.acquisition_bytes)
    thread=threading.Thread(target=lambda:_capture_result(errors,results,proxy._relay,client,upstream,limits,budget),daemon=True); thread.start()
    return client,client_peer,upstream,upstream_peer,thread,errors,results

def _recv_exact(sock,size,timeout=2):
    previous=sock.gettimeout(); deadline=time.monotonic()+timeout; data=bytearray()
    try:
        while len(data)<size:
            remaining=deadline-time.monotonic()
            if remaining<=0: raise TimeoutError("exact socket read deadline exceeded")
            sock.settimeout(remaining); chunk=sock.recv(size-len(data))
            if not chunk: raise AssertionError("socket reached EOF before exact read completed")
            data.extend(chunk)
        return bytes(data)
    finally: sock.settimeout(previous)

def _capture_result(errors,results,function,*args):
    try: results.append(function(*args))
    except Exception as exc: errors.append(exc)

def test_relay_client_half_close_preserves_late_upstream_response_until_both_eof():
    client,client_peer,upstream,upstream_peer,thread,errors,results=_relay_fixture()
    client_peer.sendall(b"request"); client_peer.shutdown(socket.SHUT_WR)
    assert _recv_exact(upstream_peer,7)==b"request" and upstream_peer.recv(1)==b""
    assert thread.is_alive()
    upstream_peer.sendall(b"late-response"); upstream_peer.shutdown(socket.SHUT_WR)
    assert _recv_exact(client_peer,13)==b"late-response" and client_peer.recv(1)==b""
    thread.join(1); assert not thread.is_alive() and not errors
    assert results==[{"client":7,"upstream":13}]
    for item in (client,client_peer,upstream,upstream_peer): item.close()

def test_relay_upstream_half_close_preserves_late_client_data_until_both_eof():
    client,client_peer,upstream,upstream_peer,thread,errors,results=_relay_fixture()
    upstream_peer.sendall(b"response"); upstream_peer.shutdown(socket.SHUT_WR)
    assert _recv_exact(client_peer,8)==b"response" and client_peer.recv(1)==b""
    assert thread.is_alive()
    client_peer.sendall(b"late-request"); client_peer.shutdown(socket.SHUT_WR)
    assert _recv_exact(upstream_peer,12)==b"late-request" and upstream_peer.recv(1)==b""
    thread.join(1); assert not thread.is_alive() and not errors
    assert results==[{"client":12,"upstream":8}]
    for item in (client,client_peer,upstream,upstream_peer): item.close()

@pytest.mark.parametrize(("limits","budget","payload","message"),[
    (proxy.ProxyLimits(duration=1,idle=0.05),proxy.AcquisitionByteBudget(20),None,"idle"),
    (proxy.ProxyLimits(direction_bytes=3,tunnel_bytes=20,duration=1,idle=0.5),proxy.AcquisitionByteBudget(20),b"four","byte limit"),
    (proxy.ProxyLimits(direction_bytes=20,tunnel_bytes=3,duration=1,idle=0.5),proxy.AcquisitionByteBudget(20),b"four","byte limit"),
    (proxy.ProxyLimits(direction_bytes=20,tunnel_bytes=20,duration=1,idle=0.5),proxy.AcquisitionByteBudget(3),b"four","acquisition-wide"),
])
def test_relay_limits_remain_enforced_after_client_half_close(limits,budget,payload,message):
    client,client_peer,upstream,upstream_peer,thread,errors,results=_relay_fixture(limits,budget)
    client_peer.shutdown(socket.SHUT_WR); assert upstream_peer.recv(1)==b""
    if payload is not None: upstream_peer.sendall(payload)
    thread.join(1); assert not thread.is_alive() and not results
    assert errors and message in str(errors[0])
    for item in (client,client_peer,upstream,upstream_peer): item.close()

def test_relay_duration_remains_enforced_after_upstream_half_close():
    limits=proxy.ProxyLimits(duration=0.05,idle=0.5); budget=proxy.AcquisitionByteBudget(20)
    client,client_peer,upstream,upstream_peer,thread,errors,results=_relay_fixture(limits,budget)
    upstream_peer.shutdown(socket.SHUT_WR); assert client_peer.recv(1)==b""
    thread.join(0.5); assert not thread.is_alive() and not results
    assert errors and "duration" in str(errors[0])
    for item in (client,client_peer,upstream,upstream_peer): item.close()

def test_relay_unregisters_eof_readers_instead_of_spinning(monkeypatch):
    factory=proxy.selectors.DefaultSelector; unregistered=[]; selected=[]; first=threading.Event()
    class TrackingSelector:
        def __init__(self): self.inner=factory()
        def register(self,*args): return self.inner.register(*args)
        def unregister(self,fileobj):
            unregistered.append(fileobj); first.set(); return self.inner.unregister(fileobj)
        def select(self,*args): selected.append(True); return self.inner.select(*args)
        def close(self): return self.inner.close()
    monkeypatch.setattr(proxy.selectors,"DefaultSelector",TrackingSelector)
    client,client_peer,upstream,upstream_peer,thread,errors,results=_relay_fixture()
    client_peer.shutdown(socket.SHUT_WR); assert first.wait(0.5)
    assert unregistered==[client] and thread.is_alive()
    observed=len(selected); time.sleep(0.05); assert len(selected)<=observed+1
    upstream_peer.shutdown(socket.SHUT_WR); thread.join(1)
    assert unregistered==[client,upstream] and not errors and results==[{"client":0,"upstream":0}]
    for item in (client,client_peer,upstream,upstream_peer): item.close()

def test_relay_half_close_backpressure_is_bounded_by_named_idle_timeout():
    client,client_peer=socket.socketpair(); upstream,upstream_peer=socket.socketpair(); errors=[]
    client.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,1024)
    client_peer.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024); client_peer.settimeout(2)
    limits=proxy.ProxyLimits(direction_bytes=8*1024**2,tunnel_bytes=8*1024**2,acquisition_bytes=8*1024**2,duration=2,idle=0.4)
    budget=proxy.AcquisitionByteBudget(limits.acquisition_bytes)
    started=time.monotonic()
    relay=threading.Thread(target=lambda:_capture_error(errors,proxy._relay,client,upstream,limits,budget)); relay.start()
    client_peer.shutdown(socket.SHUT_WR); assert upstream_peer.recv(1)==b""
    time.sleep(0.25)
    def flood():
        try: upstream_peer.sendall(b"x"*(4*1024**2)); upstream_peer.shutdown(socket.SHUT_WR)
        except OSError: pass
    sender=threading.Thread(target=flood); sender.start(); relay.join(1)
    elapsed=time.monotonic()-started
    try:
        assert not relay.is_alive() and elapsed<=limits.idle+0.15
        assert errors and str(errors[0])=="CONNECT tunnel idle limit exceeded"
    finally:
        for item in (client,client_peer,upstream,upstream_peer): item.close()
        sender.join(2)
    assert not sender.is_alive()

def test_relay_shutdown_only_tolerates_expected_socket_errors(monkeypatch):
    class Target:
        def shutdown(self,_operation): raise OSError(9,"unexpected")
    with pytest.raises(OSError,match="unexpected"): proxy._shutdown_write(Target())
    for code in (errno.ENOTCONN,errno.EPIPE,errno.ECONNRESET,errno.ESHUTDOWN):
        monkeypatch.setattr(Target,"shutdown",lambda _self,_operation,code=code:(_ for _ in ()).throw(OSError(code,"expected")))
        proxy._shutdown_write(Target())

def _capture_error(errors,function,*args):
    try: function(*args)
    except Exception as exc: errors.append(exc)

def test_acquisition_budget_is_atomic_across_concurrent_tunnels():
    budget=proxy.AcquisitionByteBudget(20); barrier=threading.Barrier(8); accepted=[]; rejected=[]
    def charge():
        barrier.wait()
        try: budget.charge(4); accepted.append(True)
        except ValueError: rejected.append(True)
    workers=[threading.Thread(target=charge) for _ in range(8)]
    for worker in workers: worker.start()
    for worker in workers: worker.join(2)
    assert all(not worker.is_alive() for worker in workers)
    assert len(accepted)==5 and len(rejected)==3 and budget.used==20

def test_acquisition_budget_rejects_chunk_before_forwarding():
    client,client_peer=socket.socketpair(); upstream,upstream_peer=socket.socketpair(); errors=[]
    limits=proxy.ProxyLimits(direction_bytes=10,tunnel_bytes=20,duration=2,idle=1)
    budget=proxy.AcquisitionByteBudget(3)
    upstream_peer.settimeout(0.1)
    thread=threading.Thread(target=lambda:_capture_error(errors,proxy._relay,client,upstream,limits,budget),daemon=True); thread.start()
    client_peer.sendall(b"four"); thread.join(2)
    assert errors and "acquisition-wide" in str(errors[0]) and budget.used==0
    with pytest.raises(TimeoutError): upstream_peer.recv(1)
    for item in (client,client_peer,upstream,upstream_peer): item.close()

def test_acquisition_budget_is_shared_across_sequential_tunnels():
    budget=proxy.AcquisitionByteBudget(6); limits=proxy.ProxyLimits(direction_bytes=10,tunnel_bytes=20,duration=2,idle=1)
    first,first_peer=socket.socketpair(); upstream,upstream_peer=socket.socketpair(); errors=[]
    thread=threading.Thread(target=lambda:_capture_error(errors,proxy._relay,first,upstream,limits,budget),daemon=True); thread.start()
    first_peer.sendall(b"four"); assert _recv_exact(upstream_peer,4)==b"four"
    first_peer.shutdown(socket.SHUT_WR); upstream_peer.shutdown(socket.SHUT_WR); thread.join(2)
    assert not thread.is_alive() and not errors and budget.used==4
    for item in (first,first_peer,upstream,upstream_peer): item.close()
    second,second_peer=socket.socketpair(); upstream,upstream_peer=socket.socketpair(); upstream_peer.settimeout(0.1)
    thread=threading.Thread(target=lambda:_capture_error(errors,proxy._relay,second,upstream,limits,budget),daemon=True); thread.start()
    second_peer.sendall(b"four"); thread.join(2)
    assert len(errors)==1 and "acquisition-wide" in str(errors[0]) and budget.used==4
    with pytest.raises(TimeoutError): upstream_peer.recv(1)
    for item in (second,second_peer,upstream,upstream_peer): item.close()

def test_server_constructs_one_shared_budget_for_all_workers():
    source=__import__("inspect").getsource(proxy.serve)
    assert "AcquisitionByteBudget(limits.acquisition_bytes)" in source
    assert "handle_connect(sock, allowed, limits, budget)" in source

def resolver_payload(address="93.184.216.34"):
    value={"records":[[socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,[address,443]]]}
    return (json.dumps(value,sort_keys=True,separators=(",",":"))+"\n").encode()

def test_resolver_uses_one_isolated_bounded_subprocess_without_multiprocessing(monkeypatch):
    calls=[]
    class Process:
        pid=71; returncode=0
        def communicate(self,timeout): calls.append(("communicate",timeout)); return resolver_payload(),None
    monkeypatch.setattr(proxy.subprocess,"Popen",lambda command,**options:calls.append((command,options)) or Process())
    records=proxy.resolve_public_records("registry.npmjs.org",2)
    command,options=calls[0]
    assert command[:6]==[sys.executable,"-I","-S","-B","-c",proxy.RESOLVER_HELPER]
    assert command[-1]=="registry.npmjs.org" and options["start_new_session"] is True
    assert options["stderr"] is subprocess.DEVNULL and options["env"]=={"PATH":"/usr/local/bin:/usr/bin:/bin"}
    assert records[0][-1]==("93.184.216.34",443) and calls[1]==("communicate",2)

@pytest.mark.parametrize("payload",[
    b'{}\n',
    b'{"records":[],"records":[]}\n',
    b'{"records": []}\n',
    b'{"records":[[2,1,6,["93.184.216.34",80]]]}\n',
    b'{"records":[[2,1,6,["93.184.216.34",443]], [2,1,6,["93.184.216.35",443]]]}\n',
])
def test_resolver_output_rejects_missing_duplicate_noncanonical_or_invalid_payload(payload):
    with pytest.raises((RuntimeError,ValueError)):
        proxy._decode_resolver_output(payload)

def test_resolver_timeout_kills_and_reaps_the_exact_process_group(monkeypatch):
    calls=[]
    class Process:
        pid=72; returncode=-signal.SIGKILL
        def communicate(self,timeout):
            calls.append(("communicate",timeout))
            if len(calls)==1: raise subprocess.TimeoutExpired(["resolver"],timeout)
            return b"",None
    monkeypatch.setattr(proxy.subprocess,"Popen",lambda *_args,**_kwargs:Process())
    monkeypatch.setattr(proxy.os,"killpg",lambda pid,sig:calls.append(("killpg",pid,sig)))
    with pytest.raises(TimeoutError,match="resolution timed out"):
        proxy.resolve_public_records("registry.npmjs.org",0.25)
    assert calls==[("communicate",0.25),("killpg",72,signal.SIGKILL),("communicate",1)]

def test_status_record_is_nonce_bound_bounded_and_mode_0600(tmp_path):
    path=tmp_path/"status.json"; status=proxy.ProxyStatus(path,"run-nonce"); status.update(accepted=1,active=1); status.update(active=-1,completed=1,client_bytes=4)
    data=json.loads(path.read_text())
    assert data["nonce"]=="run-nonce" and data["active"]==0 and data["completed"]==1
    assert path.stat().st_size<8192 and stat.S_IMODE(path.stat().st_mode)==0o600

def test_final_status_is_atomic_fresh_inode_even_without_counter_change(tmp_path):
    path=tmp_path/"status.json"; status=proxy.ProxyStatus(path,"run-nonce"); before=path.stat().st_ino
    status.finalize(); after=path.stat().st_ino
    assert after!=before and json.loads(path.read_text())["active"]==0

def test_final_status_write_failure_propagates_as_proxy_failure(tmp_path,monkeypatch):
    status=proxy.ProxyStatus(tmp_path/"status.json","run-nonce")
    monkeypatch.setattr(status,"_write",lambda:(_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError,match="disk full"): status.finalize()

def test_pid_record_is_exclusive_canonical_fsynced_mode_0600(tmp_path):
    path=tmp_path/"proxy.pid.json"; proxy._write_pid_file(path,"run-nonce")
    expected=json.dumps({"nonce":"run-nonce","pid":os.getpid()},separators=(",",":"),sort_keys=True)+"\n"
    info=path.lstat(); assert path.read_text()==expected
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode)==0o600 and info.st_nlink==1
    assert (info.st_uid,info.st_gid)==(os.getuid(),os.getgid())
    with pytest.raises(FileExistsError): proxy._write_pid_file(path,"run-nonce")
