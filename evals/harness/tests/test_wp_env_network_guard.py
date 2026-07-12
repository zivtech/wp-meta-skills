import json, re, sys
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

def test_fixture_tools_match_reviewed_commands_on_exec_workspace():
    assert set(guard.BLOCK_BUILD_COMMANDS) == {"smoke","interactivity","deprecation"}
    assert all(command.startswith("node node_modules/@wordpress/scripts/bin/wp-scripts.js build") for command in guard.BLOCK_BUILD_COMMANDS.values())
    assert "blocks/runtime-card/index.js" in guard.BLOCK_BUILD_COMMANDS["smoke"]
    assert "--experimental-modules" in guard.BLOCK_BUILD_COMMANDS["interactivity"]
    assert "blocks/deprecated-card/build" in guard.BLOCK_BUILD_COMMANDS["deprecation"]
    assert guard.PHPUNIT_COMMAND == "php vendor/bin/phpunit"

def test_only_bounded_work_tmpfs_is_executable_for_compatibility():
    work=guard.executable_work_tmpfs(1024,32)
    assert work.startswith("/work:") and "exec" in work.split(",") and "noexec" not in work
    assert {"exec","nosuid","nodev"} <= set(work.split(","))
    assert guard.TEMP_TMPFS.startswith("/tmp:") and {"noexec","nosuid","nodev"} <= set(guard.TEMP_TMPFS.split(",")) and ",exec" not in guard.TEMP_TMPFS

def test_network_disconnect_precedes_fixture_execute():
    assert guard.FIXTURE_PHASE_ORDER == ("create","start","install","disconnect","execute")

def test_every_network_probe_has_an_internal_timeout():
    probes=[probe for probe in guard.runtime_probe_specs(["docker","compose"]) if probe.get("network")]
    assert probes and all(probe.get("self_timeout") is True for probe in probes)
    for probe in probes:
        command=" ".join(probe["command"])
        if "fetch(" in command: assert "AbortSignal.timeout" in command
        if "resolve4" in command: assert "Resolver({timeout:" in command and "tries:1" in command
    php_routes=next(probe for probe in probes if probe["name"]=="php-routes-denied")
    assert "example.com" not in " ".join(php_routes["command"])
    php_dns=next(probe for probe in probes if probe["name"]=="php-public-dns-denied")
    assert php_dns["allowed"]=={0,124} and "timeout 5" in " ".join(php_dns["command"])

def test_database_probe_uses_native_wordpress_database_oracle():
    probe=next(probe for probe in guard.runtime_probe_specs(["docker","compose"]) if probe["name"]=="cli-db-ready")
    command=" ".join(probe["command"])
    assert "mysqli_report(MYSQLI_REPORT_OFF)" in command and "wp core install" in command and "wp option get siteurl" in command
    assert "wp db check" not in command

def test_named_probe_errors_identify_probe_and_bound_output(monkeypatch):
    monkeypatch.setattr(guard.provision,"run_capped",lambda *_args,**_kwargs:{"returncode":7,"stdout":"out","stderr":"err"})
    with pytest.raises(RuntimeError,match="probe browser-public-http-denied failed rc=7"):
        guard.run_named_probe({"name":"browser-public-http-denied","command":["probe"],"timeout":8})
    def timeout(*_args,**_kwargs): raise RuntimeError("command timed out")
    monkeypatch.setattr(guard.provision,"run_capped",timeout)
    with pytest.raises(RuntimeError,match="probe browser-public-http-denied raised RuntimeError"):
        guard.run_named_probe({"name":"browser-public-http-denied","command":["probe"],"timeout":8})

def test_fixture_build_commands_match_reviewed_packet_scripts():
    examples=HARNESS.parent / "suites" / "wordpress-block-executor" / "examples"
    for name in ("smoke","interactivity","deprecation"):
        text=(examples / f"{name}-wordpress-v1.materializable-packet.md").read_text(encoding="utf-8")
        package=json.loads(re.search(r"### package\.json\n```json\n(.*?)\n```",text,re.S).group(1))
        expected=package["scripts"]["build"].replace(
            "wp-scripts",
            "node node_modules/@wordpress/scripts/bin/wp-scripts.js",
            1,
        )
        assert guard.BLOCK_BUILD_COMMANDS[name] == expected

def test_compatibility_failure_names_phase_and_bounds_output():
    error=guard.compatibility_failure("smoke","execute",{"returncode":137,"stdout":"x"*4000,"stderr":""},'{"OOMKilled":true}')
    message=str(error)
    assert "smoke execute failed with return code 137" in message
    assert "OOMKilled" in message
    assert len(message) < 3300

def test_canary_is_internal_digest_only_and_bounded():
    assert guard.validate_compose(guard.canary_compose())

def test_flat_wordpress_image_metadata_allowlist_rejects_inherited_runtime_state():
    config={"Hostname":"","Domainname":"","AttachStdin":False,"AttachStdout":False,"AttachStderr":False,"Tty":False,"OpenStdin":False,"StdinOnce":False,"Cmd":None,"Image":"","Volumes":None,"OnBuild":None,"Labels":None,**guard.WORDPRESS_IMAGE_ACTIVE_CONFIG}
    assert guard.validate_wordpress_image_config(config)
    for field,value in (("Volumes",{"/var/www/html":{}}),("Cmd",["apache2-foreground"]),("Labels",{"surprise":"true"}),("Healthcheck",{"Test":["CMD","true"]})):
        mutated=dict(config); mutated[field]=value
        with pytest.raises(RuntimeError,match="metadata"): guard.validate_wordpress_image_config(mutated)

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

def test_execute_failure_diagnostic_is_bounded_and_nonsecret(monkeypatch):
    calls=[]
    def fake(command,**kwargs):
        calls.append((command,kwargs)); return {"returncode":0,"stdout":"bounded","stderr":""}
    monkeypatch.setattr(guard.provision,"run_capped",fake)
    evidence=guard.execute_failure_diagnostic("fixture-123","node")
    assert set(evidence)=={"container","runtime","state","limits","stats","processes","filesystem"}
    assert all(kwargs=={"timeout":15,"limit":32768} for _command,kwargs in calls)
    flattened=" ".join(" ".join(command) for command,_kwargs in calls)
    assert "env" not in flattened.lower()
    assert "cat /work" not in flattened

def test_execute_failure_preserves_original_return_code(monkeypatch,tmp_path):
    monkeypatch.setattr(guard.materializer,"materialize_packet",lambda *_args,**_kwargs:{"pass":True})
    monkeypatch.setattr(guard,"execute_failure_diagnostic",lambda *_args:{"state":{"returncode":0,"stdout":"running","stderr":""}})
    def fake(command,**_kwargs):
        if command[:2]==["docker","exec"] and "wp-scripts.js" in " ".join(command): return {"returncode":37,"stdout":"","stderr":""}
        return {"returncode":0,"stdout":"","stderr":""}
    monkeypatch.setattr(guard.provision,"run_capped",fake)
    with pytest.raises(RuntimeError,match="return code 37"):
        guard.prove_fixture_locks(tmp_path,{"node":{"amd64":"sha256:"+"1"*64},"composer":{"amd64":"sha256:"+"2"*64}},"x86_64")
