import hashlib, json, sys
from pathlib import Path
HARNESS=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(HARNESS))
import runtime_image_provision as provision

def test_inventory_is_digest_pinned_and_complete():
    data=provision.inventory()
    assert set(data["images"]) == {"node","composer","python","playwright","wordpress","wordpress_cli","database"}
    for image in data["images"].values():
        assert all(image[k].startswith("sha256:") and len(image[k])==71 for k in ("index","amd64","arm64"))

def test_core_pin_is_exact():
    core=provision.inventory()["wordpress_core"]
    assert core == {"version":"7.0.1","url":"https://wordpress.org/wordpress-7.0.1.tar.gz","sha256":"dc10592da9b580c7525632850e0cced371b13081853ac29afe93b5d5bb00db98"}

def test_build_input_hashes_match_committed_sources():
    for relative, expected in provision.inventory()["build_inputs"].items():
        assert hashlib.sha256((HARNESS / relative).read_bytes()).hexdigest() == expected

def test_wordpress_checksum_argument_is_in_final_build_stage():
    dockerfile=(HARNESS / "runtime-images/wordpress/Dockerfile").read_text(encoding="utf-8")
    final_stage=dockerfile.split("FROM ${WORDPRESS_BASE}",1)[1]
    assert "ARG WP_CLI_SHA256" in final_stage.split("COPY wordpress.tar.gz",1)[0]
    assert 'echo "$WP_CLI_SHA256  /usr/local/bin/wp" | sha256sum -c -' in final_stage

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

def test_capped_transport():
    result=provision.run_capped(["/bin/sh","-c","printf ok"])
    assert result == {"returncode":0,"stdout":"ok","stderr":""}

def test_capped_transport_kills_during_overflow():
    import pytest
    with pytest.raises(RuntimeError, match="stdout output limit"):
        provision.run_capped(["/bin/sh","-c","while :; do printf 1234567890; done"],limit=1024,timeout=5)

def test_capped_transport_caps_stderr_independently():
    import pytest
    with pytest.raises(RuntimeError, match="stderr output limit"):
        provision.run_capped(["/bin/sh","-c","while :; do printf 1234567890 >&2; done"],limit=1024,timeout=5)

def test_capped_transport_uses_total_deadline_and_reaps_child():
    import pytest, time
    started=time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        provision.run_capped(["/bin/sh","-c","sleep 30"],timeout=0.1)
    assert time.monotonic()-started < 3

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
