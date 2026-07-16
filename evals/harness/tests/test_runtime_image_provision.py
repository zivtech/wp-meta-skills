import hashlib, json, os, sys, time
from pathlib import Path
import pytest
HARNESS=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(HARNESS))
import runtime_image_provision as provision
import wp_runtime_provisioning as runtime_provisioning
import wp_runtime_evidence
from wp_runtime_evidence import scrub_tail

def capture_processes(monkeypatch):
    processes=[]; real_popen=provision.subprocess.Popen
    def launch(*args,**kwargs):
        process=real_popen(*args,**kwargs); processes.append(process); return process
    monkeypatch.setattr(provision.subprocess,"Popen",launch)
    return processes

def assert_reaped(process):
    assert process.poll() is not None
    with pytest.raises(ProcessLookupError): os.killpg(process.pid,0)
    assert process.stdout.closed and process.stderr.closed

def test_inventory_is_digest_pinned_and_complete():
    data=provision.inventory()
    assert set(data["images"]) == {"node","composer","python","playwright","wordpress","wordpress_cli","database"}
    for image in data["images"].values():
        assert all(image[k].startswith("sha256:") and len(image[k])==71 for k in ("index","amd64","arm64"))

def test_core_pin_is_exact():
    core=provision.inventory()["wordpress_core"]
    assert core == {"version":"7.0.1","url":"https://wordpress.org/wordpress-7.0.1.tar.gz","sha256":"dc10592da9b580c7525632850e0cced371b13081853ac29afe93b5d5bb00db98"}


def test_plugin_check_pin_is_exact_and_copied_before_generated_artifact():
    item=provision.inventory()["plugin_check"]
    assert item=={
        "version":"2.0.0","url":"https://downloads.wordpress.org/plugin/plugin-check.2.0.0.zip",
        "sha256":"d744ee1f93866527aedf7d0a73df40bd87018f02cd5465fa39230bf4c2b3a3fa",
        "license":"GPL-2.0-or-later",
    }
    dockerfile=(HARNESS/"runtime-images/wordpress/Dockerfile").read_text(encoding="utf-8")
    assert "PLUGIN_CHECK_SHA256" in dockerfile
    assert "/var/www/html/wp-content/plugins/plugin-check" in dockerfile


def test_shared_runtime_context_prepares_core_and_plugin_check(monkeypatch,tmp_path):
    monkeypatch.setattr(provision,"download_core",
        lambda target,**_kwargs:target.write_bytes(b"core"))
    monkeypatch.setattr(provision,"download_pinned",
        lambda _item,target,**_kwargs:target.write_bytes(b"plugin-check"))
    wordpress,database,browser=runtime_provisioning.prepare_build_contexts(
        tmp_path,provision.inventory(),
    )
    assert (wordpress/"wordpress.tar.gz").read_bytes()==b"core"
    assert (wordpress/"plugin-check.zip").read_bytes()==b"plugin-check"
    assert (database/"Dockerfile").is_file() and (browser/"Dockerfile").is_file()

def test_build_input_hashes_match_committed_sources():
    for relative, expected in provision.inventory()["build_inputs"].items():
        assert hashlib.sha256((HARNESS / relative).read_bytes()).hexdigest() == expected

def test_wordpress_checksum_argument_is_in_final_build_stage():
    dockerfile=(HARNESS / "runtime-images/wordpress/Dockerfile").read_text(encoding="utf-8")
    prepared_stage=dockerfile.split("FROM ${WORDPRESS_BASE} AS prepared",1)[1]
    assert "ARG WP_CLI_SHA256" in prepared_stage.split("COPY wordpress.tar.gz",1)[0]
    assert 'echo "$WP_CLI_SHA256  /usr/local/bin/wp" | sha256sum -c -' in prepared_stage

def test_wordpress_final_stage_drops_inherited_volume_metadata():
    dockerfile=(HARNESS / "runtime-images/wordpress/Dockerfile").read_text(encoding="utf-8")
    final_stage=dockerfile.rsplit("FROM scratch",1)[1]
    assert "COPY --from=prepared / /" in final_stage
    assert "VOLUME" not in final_stage
    assert "WORKDIR /var/www/html" in final_stage
    assert "USER www-data" in final_stage
    assert "ENTRYPOINT" in final_stage

def test_database_seed_and_runtime_share_bounded_redo_log_size():
    dockerfile=(HARNESS / "runtime-images/database/Dockerfile").read_text(encoding="utf-8")
    entrypoint=(HARNESS / "runtime-images/database/entrypoint.sh").read_text(encoding="utf-8")
    assert "--innodb-log-file-size=16M" in dockerfile
    assert "--innodb-log-file-size=16M" in entrypoint

def test_platform_resolution_blocks_unknown():
    item=provision.inventory()["images"]["node"]
    assert provision.platform_digest(item,"x86_64")==item["amd64"]
    import pytest
    with pytest.raises(RuntimeError): provision.platform_digest(item,"riscv64")

def test_architecture_aliases_normalize_for_host_and_docker_reports():
    assert provision.normalize_arch("x86_64") == "amd64"
    assert provision.normalize_arch("amd64") == "amd64"
    assert provision.normalize_arch("aarch64") == "arm64"
    assert provision.normalize_arch("arm64") == "arm64"


def test_generated_runtime_requires_docker_engine_28_isolated_gateway_mode(monkeypatch):
    result={"returncode":0,"stdout":"28.5.1\n","stderr":""}
    monkeypatch.setattr(runtime_provisioning,"_run",lambda *_args,**_kwargs:result)
    assert runtime_provisioning._require_isolated_gateway_mode()=="28.5.1"
    for version in ("27.5.1","not-a-version"):
        result["stdout"]=version
        with pytest.raises(RuntimeError,match="Docker Engine 28"):
            runtime_provisioning._require_isolated_gateway_mode()

def test_capped_transport():
    result=provision.run_capped(["/bin/sh","-c","printf ok"])
    assert result == {"returncode":0,"stdout":"ok","stderr":""}

def test_capped_transport_kills_during_overflow(monkeypatch):
    processes=capture_processes(monkeypatch)
    with pytest.raises(RuntimeError, match="stdout output limit"):
        provision.run_capped(["/bin/sh","-c","while :; do printf 1234567890; done"],limit=1024,timeout=5)
    assert len(processes)==1; assert_reaped(processes[0])

def test_capped_transport_caps_stderr_independently(monkeypatch):
    processes=capture_processes(monkeypatch)
    with pytest.raises(RuntimeError, match="stderr output limit"):
        provision.run_capped(["/bin/sh","-c","while :; do printf 1234567890 >&2; done"],limit=1024,timeout=5)
    assert len(processes)==1; assert_reaped(processes[0])

def test_capped_transport_uses_total_deadline_and_reaps_child(monkeypatch):
    processes=capture_processes(monkeypatch)
    started=time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        provision.run_capped(["/bin/sh","-c","sleep 30"],timeout=0.1)
    assert time.monotonic()-started < provision.CLEANUP_SECONDS+1
    assert len(processes)==1; assert_reaped(processes[0])

def test_capped_transport_closed_pipes_do_not_bypass_operation_deadline(monkeypatch):
    processes=capture_processes(monkeypatch); started=time.monotonic()
    with pytest.raises(RuntimeError,match="timed out"):
        provision.run_capped(["/bin/sh","-c","exec 1>&-; exec 2>&-; sleep 30"],timeout=0.1)
    assert time.monotonic()-started < provision.CLEANUP_SECONDS+1
    assert len(processes)==1; assert_reaped(processes[0])

def test_capped_transport_setup_error_reaps_owned_group(monkeypatch):
    processes=capture_processes(monkeypatch)
    monkeypatch.setattr(provision.threading,"Thread",lambda *_args,**_kwargs:(_ for _ in ()).throw(RuntimeError("thread setup failed")))
    with pytest.raises(RuntimeError,match="thread setup failed"):
        provision.run_capped(["/bin/sh","-c","sleep 30"],timeout=5)
    assert len(processes)==1; assert_reaped(processes[0])

def test_core_download_streams_and_verifies(monkeypatch, tmp_path):
    import io
    payload=b"reviewed-core"
    class Response(io.BytesIO):
        headers={"Content-Length":str(len(payload))}
        def __enter__(self): return self
        def __exit__(self,*args): self.close()
    monkeypatch.setattr(provision.urllib.request,"urlopen",lambda *_args,**_kwargs:Response(payload))
    monkeypatch.setattr(provision,"inventory",lambda:{"wordpress_core":{"url":"https://wordpress.test/core.tgz","sha256":hashlib.sha256(payload).hexdigest()}})
    target=tmp_path/"core.tgz"
    assert provision.download_core(target)==hashlib.sha256(payload).hexdigest()
    assert target.read_bytes()==payload

def test_core_download_removes_oversized_partial(monkeypatch, tmp_path):
    import io, pytest
    class Response(io.BytesIO):
        headers={"Content-Length":str(65*1024*1024)}
        def __enter__(self): return self
        def __exit__(self,*args): self.close()
    monkeypatch.setattr(provision.urllib.request,"urlopen",lambda *_args,**_kwargs:Response(b"x"))
    target=tmp_path/"core.tgz"
    with pytest.raises(RuntimeError,match="byte limit"): provision.download_core(target)
    assert not target.exists()

def test_runner_locks_have_reviewed_root_integrity():
    expected = {
        "browser-runner": ("node_modules/playwright", "1.58.0"),
        "wp-env-runner": ("node_modules/@wordpress/env", "11.10.0"),
    }
    for runner, (key, version) in expected.items():
        lock=json.loads((HARNESS / runner / "package-lock.json").read_text(encoding="utf-8"))
        assert lock["packages"][key]["version"] == version
        assert lock["packages"][key]["integrity"].startswith("sha512-")

def test_fixture_locks_are_exact_and_composer_is_dist_only():
    suites=HARNESS.parent / "suites"
    block_files=("smoke", "interactivity", "deprecation")
    import materialize_wordpress_executor_packet as materializer
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        for name in block_files:
            packet=suites / f"wordpress-block-executor/examples/{name}-wordpress-v1.materializable-packet.md"
            out=root/name; assert materializer.materialize_packet("block",packet.read_text(),out)["pass"]
            lock=json.loads((out/"package-lock.json").read_text())
            assert lock["packages"]["node_modules/@wordpress/scripts"]["version"] == "32.4.1"
        packet=suites / "wordpress-plugin-executor/examples/phpunit-wordpress-v1.materializable-packet.md"
        out=root/"phpunit"; assert materializer.materialize_packet("plugin",packet.read_text(),out)["pass"]
        lock=json.loads((out/"acme-runtime-tested/composer.lock").read_text())
        assert next(p for p in lock["packages-dev"] if p["name"]=="phpunit/phpunit")["version"] == "12.5.31"
        for package in lock["packages"]+lock["packages-dev"]:
            assert package["dist"]["type"] == "zip"
            assert package["dist"]["url"].startswith("https://")
            assert package["dist"]["reference"]
            assert package.get("type") != "composer-plugin"


def test_runtime_image_cleanup_proves_every_tag_absent(monkeypatch):
    commands=[]
    def run(command,**_kwargs):
        commands.append(command)
        if command[1:3]==["image","inspect"]:
            return {"returncode":1,"stdout":"","stderr":"Error: No such image"}
        return {"returncode":0,"stdout":"","stderr":""}
    monkeypatch.setattr(runtime_provisioning.provision,"run_capped",run)
    result=runtime_provisioning._cleanup_image_tags(("one:tag","two:tag"))
    assert result["state"]=="removed" and result["remaining"]==[]
    assert [command[-1] for command in commands if command[1:3]==["image","inspect"]]==["one:tag","two:tag"]


def test_runtime_image_cleanup_retains_unknown_or_present_tags(monkeypatch):
    def run(command,**_kwargs):
        if command[-1]=="unknown:tag": raise RuntimeError("daemon unavailable")
        if command[1:3]==["image","inspect"]:
            return {"returncode":0,"stdout":"sha256:present","stderr":""}
        return {"returncode":1,"stdout":"","stderr":"remove failed"}
    monkeypatch.setattr(runtime_provisioning.provision,"run_capped",run)
    result=runtime_provisioning._cleanup_image_tags(("present:tag","unknown:tag"))
    assert result["state"]=="retained"
    assert result["remaining"]==["present:tag","unknown:tag"]
    assert result["recovery"]==[
        "docker image rm -f present:tag","docker image rm -f unknown:tag",
    ]


def test_runtime_diagnostics_scrub_quoted_and_unquoted_credentials():
    value='{"token":"secret-value","password": "another"} api_key=third'
    scrubbed=scrub_tail(value)
    assert "secret-value" not in scrubbed and "another" not in scrubbed and "third" not in scrubbed
    assert scrubbed.count("[REDACTED]")==3


@pytest.mark.parametrize("header", [
    "Authorization: Bearer BEARER-CANARY-123",
    "Authorization: Basic BASIC-CANARY-456",
    "Proxy-Authorization: Basic PROXY-CANARY-789",
    "Cookie: first=value; second=COOKIE-CANARY-123",
    "Set-Cookie: session=SET-COOKIE-CANARY-456; HttpOnly",
    "Authorization=Bearer EQUALS-BEARER-CANARY-123",
    "Proxy-Authorization = Basic EQUALS-PROXY-CANARY-456",
    "Cookie=first=value; second=EQUALS-COOKIE-CANARY-789",
])
def test_runtime_diagnostics_scrub_complete_http_credential_headers(header):
    scrubbed = scrub_tail(f"before\n{header}\nafter")

    assert "CANARY" not in scrubbed
    assert "after" in scrubbed
    assert "[REDACTED]" in scrubbed


def test_runtime_diagnostics_redact_before_taking_the_final_tail():
    credential = "x" * 500 + "LONG-CREDENTIAL-CANARY"

    scrubbed = scrub_tail(f"Authorization: Bearer {credential}", limit=40)

    assert "CANARY" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_runtime_cleanup_uses_a_separate_bounded_deadline(monkeypatch):
    now=[100.0]
    monkeypatch.setattr(wp_runtime_evidence.time,"monotonic",lambda:now[0])
    deadline=wp_runtime_evidence.RuntimeDeadline.start(30)
    now[0]=131.0
    with pytest.raises(TimeoutError): deadline.remaining(1)
    deadline.begin_cleanup()
    assert deadline.remaining(500,cleanup=True)==180.0
    now[0]=312.0
    with pytest.raises(TimeoutError): deadline.remaining(1,cleanup=True)
