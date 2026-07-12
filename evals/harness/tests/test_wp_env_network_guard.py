import sys
from pathlib import Path
HARNESS=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(HARNESS))
import pytest, wp_env_network_guard as guard

def test_trusted_fixture_copy_does_not_preserve_host_ownership():
    assert "cp -R" in guard.COPY_INPUT_COMMAND
    assert "cp -a" not in guard.COPY_INPUT_COMMAND
    assert "preserve" not in guard.COPY_INPUT_COMMAND

def test_trusted_installs_use_only_bounded_workspace_homes_and_caches():
    assert "HOME=/work/home" in guard.PREPARE_WORK_ENV
    assert "npm_config_cache=/work/.npm-cache" in guard.PREPARE_WORK_ENV
    assert "COMPOSER_HOME=/work/.composer" in guard.PREPARE_WORK_ENV
    assert "/root" not in guard.PREPARE_WORK_ENV

def test_trusted_runner_workspaces_have_reviewed_separate_bounds():
    assert guard.TRUSTED_RUNNER_LIMITS["browser-runner"] == {"memory":"1g","size":536870912,"inodes":50000}
    assert guard.TRUSTED_RUNNER_LIMITS["wp-env-runner"] == {"memory":"3g","size":2147483648,"inodes":200000}

def test_canary_is_internal_digest_only_and_bounded():
    assert guard.validate_compose(guard.canary_compose())

def test_rejects_added_service():
    spec=guard.canary_compose(); spec["services"]["surprise"]={}
    with pytest.raises(RuntimeError,match="unlisted"): guard.validate_compose(spec)

def test_rejects_unbounded_tmpfs():
    spec=guard.canary_compose(); spec["services"]["browser"]["tmpfs"]=["/tmp"]
    with pytest.raises(RuntimeError,match="unbounded"): guard.validate_compose(spec)

def test_live_boundary_is_blocked_off_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(guard.platform,"system",lambda:"Darwin")
    assert guard.run_linux_canary(tmp_path/"never-created")["status"] == "blocked"
    assert not (tmp_path/"never-created").exists()

def test_linux_wrapper_uses_and_cleans_plan006_lease(monkeypatch, tmp_path):
    monkeypatch.setattr(guard.platform,"system",lambda:"Linux")
    def fake_run(root):
        assert (root/".workspace-lease").is_file(); (root/"evidence").write_text("ok"); return {"status":"pass"}
    monkeypatch.setattr(guard,"_run_linux_canary",fake_run)
    monkeypatch.setattr(guard.provision,"run_capped",lambda *_args,**_kwargs:{"returncode":0,"stdout":"","stderr":""})
    requested=tmp_path/"lease"
    assert guard.run_linux_canary(requested)["status"]=="pass"
    assert not requested.exists()

def test_services_have_complete_static_resource_policy():
    for service in guard.canary_compose()["services"].values():
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["pids_limit"] == 128
        assert service["mem_limit"] == "512m"
        assert service["cpus"] == "1.0"
        assert service["logging"] == {"driver":"none"}
        assert service["user"].replace(":","").isdigit()

@pytest.mark.parametrize("field,value",[("volumes",["/:/host"]),("devices",["/dev/null"]),("privileged",True),("ports",["8080:8080"]),("extra_hosts",["host:host-gateway"]),("environment",{"HTTP_PROXY":"http://proxy"}),("dns",["8.8.8.8"]),("network_mode","host")])
def test_rejects_forbidden_service_surface(field,value):
    spec=guard.canary_compose(); spec["services"]["wordpress"][field]=value
    with pytest.raises(RuntimeError,match="unknown"): guard.validate_compose(spec)

def test_rejects_cpu_user_and_tmpfs_option_drift():
    for mutation in (lambda s:s["services"]["browser"].update(cpus="2.0"),lambda s:s["services"]["browser"].update(user="pwuser"),lambda s:s["services"]["browser"].update(tmpfs=["/tmp:uid=1000,gid=1000,mode=0777,size=1,nr_inodes=1"])):
        spec=guard.canary_compose(); mutation(spec)
        with pytest.raises(RuntimeError): guard.validate_compose(spec)

def test_rejects_network_command_and_entrypoint_drift():
    mutations=(lambda s:s["services"]["browser"].update(networks=["wp_db"]),lambda s:s["services"]["browser"].update(command=["sh"]),lambda s:s["services"]["cli"].update(entrypoint=["sh"]),lambda s:s["services"]["wordpress"].update(command=["sh"]))
    for mutation in mutations:
        spec=guard.canary_compose(); mutation(spec)
        with pytest.raises(RuntimeError): guard.validate_compose(spec)

def test_buildx_manifest_formatter_real_shape_regression():
    payload='{"schemaVersion":2,"mediaType":"application/vnd.oci.image.index.v1+json","digest":"sha256:index","size":123,"manifests":[{"digest":"sha256:amd","platform":{"architecture":"amd64","os":"linux"}},{"digest":"sha256:arm","platform":{"architecture":"arm64","os":"linux"}}]}'
    assert guard.parse_tag_manifest(payload,"amd64")==("sha256:index","sha256:amd")
    with pytest.raises(RuntimeError): guard.parse_tag_manifest('{"schemaVersion":2,"manifests":[]}',"amd64")

def test_wp_cli_verification_fails_closed():
    guard.verify_wp_cli_result({"returncode":0,"stdout":"abc  /usr/local/bin/wp","stderr":""},"abc")
    with pytest.raises(RuntimeError,match="WP-CLI"):
        guard.verify_wp_cli_result({"returncode":1,"stdout":"","stderr":"bad"},"abc")
    with pytest.raises(RuntimeError,match="WP-CLI"):
        guard.verify_wp_cli_result({"returncode":0,"stdout":"wrong file","stderr":""},"abc")

def test_outer_cleanup_preserves_inspection_failure(monkeypatch,tmp_path):
    monkeypatch.setattr(guard.platform,"system",lambda:"Linux")
    monkeypatch.setattr(guard,"_run_linux_canary",lambda _root:(_ for _ in ()).throw(RuntimeError("inspection failure")))
    cleanups=[]
    monkeypatch.setattr(guard.provision,"run_capped",lambda command,**_kwargs:cleanups.append(command) or {"returncode":1,"stdout":"","stderr":"cleanup failed"})
    with pytest.raises(RuntimeError,match="inspection failure"): guard.run_linux_canary(tmp_path/"lease")
    assert cleanups and cleanups[-1][0:3]==["docker","image","rm"]
    assert not (tmp_path/"lease").exists()

def test_df_profile_parses_with_documented_rounding_tolerance():
    result=guard.validate_df_profile("tmpfs 32769 1 32768 1% /tmp\ntmpfs 2064 1 2063 1% /tmp",32*1024*1024,2048)
    assert result["block_rounding_tolerance"]==1
    assert result["inode_rounding_tolerance"]==21

@pytest.mark.parametrize("payload",["","tmpfs bad 1\ntmpfs 10 1","only one line"])
def test_df_profile_missing_or_unparsed_fails_closed(payload):
    with pytest.raises(RuntimeError,match="missing or unparsed"): guard.validate_df_profile(payload,1024,10)

@pytest.mark.parametrize("payload",["tmpfs 102 1 1 1% /tmp\ntmpfs 10 1 1 1% /tmp","tmpfs 1 1 1 1% /tmp\ntmpfs 100 1 1 1% /tmp"])
def test_df_profile_oversized_fails_closed(payload):
    with pytest.raises(RuntimeError,match="exceeds"): guard.validate_df_profile(payload,1024,10)
