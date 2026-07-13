import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))
import step4_evidence


SHA = "a" * 40


def identity(profile_id):
    profile=step4_evidence.dependency_egress_proxy.ACQUISITION_PROFILES[profile_id]; inventory=step4_evidence.runtime_image_provision.inventory()["images"]
    package=inventory[profile.image_key]; proxy=inventory["python"]; container_digits=("8","9") if profile.kind=="npm" else ("a","b")
    limits=step4_evidence.EXPECTED_LIMITS|{"admission_required_bytes":sum(step4_evidence.EXPECTED_LIMITS.values())}
    return {"profile_id":profile_id,"manifest_sha256":profile.manifest_sha256,"lock_sha256":profile.lock_sha256,"package_image_ref":f"{package['tag'].split(':')[0]}@{profile.amd64_digest}","proxy_image_ref":f"{proxy['tag'].split(':')[0]}@{proxy['amd64']}","package_local_image_id":"sha256:"+"6"*64,"proxy_local_image_id":"sha256:"+"7"*64,"package_container_id":container_digits[0]*64,"proxy_container_id":container_digits[1]*64,"package_observed_image_id":"sha256:"+"6"*64,"proxy_observed_image_id":"sha256:"+"7"*64,"toolchain_versions":list(profile.versions),"runner_os":"Linux","runner_arch":"amd64",**limits}


def lifecycle(profile_id="block-scripts-32.4.1-smoke"):
    token=("a" if profile_id=="block-scripts-32.4.1-smoke" else "b")*16; names={"package":f"wp-package-{token}","proxy":f"wp-acquire-proxy-{token}","internal":f"wp-acquire-internal-{token}","egress":f"wp-acquire-egress-{token}","lease":f"/tmp/wp-meta-skills-artifact-execution-{token}"}
    events=[{"kind":"container","name":names["package"],"state":"created"},{"kind":"container","name":names["proxy"],"state":"created"},{"kind":"network","name":names["internal"],"state":"created"},{"kind":"network","name":names["egress"],"state":"created"},{"kind":"lease","name":names["lease"],"state":"created"},{"kind":"network","name":names["internal"],"state":"attached"},{"kind":"network","name":names["internal"],"state":"attached"},{"kind":"network","name":names["egress"],"state":"attached"},{"kind":"container","name":names["package"],"state":"detached"},{"kind":"container","name":names["proxy"],"state":"removed"},{"kind":"network","name":names["internal"],"state":"detached"},{"kind":"network","name":names["egress"],"state":"detached"},{"kind":"network","name":names["internal"],"state":"removed"},{"kind":"network","name":names["egress"],"state":"removed"},{"kind":"lease","name":names["lease"],"state":"removed"},{"kind":"container","name":names["package"],"state":"removed"}]
    cleanup=[item for item in events if item["state"] in {"removed","detached","retained"}]
    timings={key:0.1 for key in step4_evidence.TIMING_KEYS}; timings["end_to_end"]=1.0
    metrics={"mem_available":4*1024**3,"proxy_memory_peak":64*1024**2,"package_memory_peak_pre_export":256*1024**2,"workspace_bytes_used_pre_export":100*1024**2,"package_memory_peak":300*1024**2,"workspace_bytes_used":110*1024**2}
    return {"cleanup_events":cleanup,"final_status":"pass","identity":identity(profile_id),"metrics":metrics,"resource_events":events,"timings_seconds":timings}


def controlled():
    relay = "wp-relay-1234"; token="c"*12; internal=f"wp-fake-internal-{token}"; egress=f"wp-fake-egress-{token}"
    topology={
        "containers": {
            "package": {"id": "1" * 64, "name":f"wp-package-fake-{token}", "ips": {internal: "172.20.0.2"}},
            "proxy": {"id": "2" * 64, "name":f"wp-proxy-fake-{token}", "ips": {internal: "172.20.0.3", egress: "93.184.216.35"}},
            "registry": {"id": "3" * 64, "name":f"wp-registry-fake-{token}", "ips": {egress: "93.184.216.34"}},
        },
        "networks": {
            "internal": {"id": "4" * 64, "name": internal, "internal": True, "subnet": "172.20.0.0/16", "gateway": "172.20.0.1"},
            "egress": {"id": "5" * 64, "name": egress, "internal": False, "subnet": step4_evidence.FAKE_PUBLIC_SUBNET, "gateway": step4_evidence.FAKE_PUBLIC_GATEWAY},
        },
    }
    removed={kind:{role:{"id":item["id"],"name":item["name"]} for role,item in topology[kind].items()} for kind in ("containers","networks")}
    return {
        "cleanup_disposition": {"complete": True, "retained": [], "removed":removed},
        "proxy_status": {"nonce": "wp-status-1234", "accepted": 1, "active": 0, "completed": 1, "rejected": 0, "client_bytes": len(relay), "upstream_bytes": len(relay)},
        "relay_nonce": relay,
        "run_nonce": "wp-status-1234",
        "topology": topology,
    }


def test_three_atomic_exact_sha_legs_combine_to_bounded_packet(tmp_path):
    evidence = tmp_path / "legs"; evidence.mkdir(mode=0o700)
    step4_evidence.write_leg("npm_lifecycle", lifecycle(), evidence, SHA)
    step4_evidence.write_leg("composer_lifecycle", lifecycle("plugin-phpunit-12.5.31"), evidence, SHA)
    step4_evidence.write_leg("controlled_connect", controlled(), evidence, SHA)
    for path in evidence.iterdir():
        assert path.stat().st_size <= step4_evidence.PER_LEG_LIMIT
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    output = tmp_path / "combined.json"
    step4_evidence.combine_records(evidence, output, SHA, 0, 123)
    packet = json.loads(output.read_text())
    assert packet["commit_sha"] == SHA and packet["pytest_status"] == 0 and packet["duration_seconds"] == 123
    assert set(packet["legs"]) == set(step4_evidence.LEGS) and output.stat().st_size <= step4_evidence.COMBINED_LIMIT


def test_lifecycle_payload_merges_live_container_and_observed_image_identity():
    expected=lifecycle(); runtime_keys={"package_container_id","proxy_container_id","package_observed_image_id","proxy_observed_image_id"}|set(step4_evidence.LIMIT_KEYS)
    base={key:value for key,value in expected["identity"].items() if key not in runtime_keys}; runtime={key:expected["identity"][key] for key in runtime_keys}
    detail={key:expected[key] for key in ("metrics","resource_events","timings_seconds")}
    result=SimpleNamespace(detail=json.dumps(detail),runtime_identity=runtime,status="pass")
    observed=step4_evidence.lifecycle_payload(result,base)
    assert observed["identity"]==expected["identity"] and observed["cleanup_events"]==expected["cleanup_events"]


def test_leg_write_rejects_duplicate_bad_sha_and_oversize(tmp_path):
    evidence = tmp_path / "legs"; evidence.mkdir()
    step4_evidence.write_leg("npm_lifecycle", lifecycle(), evidence, SHA)
    with pytest.raises(RuntimeError, match="fresh"): step4_evidence.write_leg("npm_lifecycle", lifecycle(), evidence, SHA)
    with pytest.raises(ValueError, match="commit SHA"): step4_evidence.write_leg("composer_lifecycle", lifecycle("plugin-phpunit-12.5.31"), evidence, "bad")
    with pytest.raises(ValueError, match="limit"): step4_evidence.write_leg("composer_lifecycle", {"x": "x" * step4_evidence.PER_LEG_LIMIT}, evidence, SHA)


def deeply_nested():
    value=0
    for _index in range(step4_evidence.MAX_DEPTH+2): value={"x":value}
    return value


@pytest.mark.parametrize("payload",[
    {"x":"x"*(step4_evidence.MAX_STRING_CHARACTERS+1)},
    {"x":"🙂"*5000},
    {"x"*(step4_evidence.MAX_KEY_CHARACTERS+1):1},
    list(range(step4_evidence.MAX_COLLECTION_LENGTH+1)),
    [[index]*10 for index in range(500)],
    deeply_nested(),
    1<<300,
    float("nan"),
])
def test_serialization_preflight_rejects_pathological_shapes_before_json_dumps(payload,monkeypatch):
    called=[]; original=step4_evidence.json.dumps
    def observed(*args,**kwargs): called.append(True); return original(*args,**kwargs)
    monkeypatch.setattr(step4_evidence.json,"dumps",observed)
    with pytest.raises(ValueError): step4_evidence._encode(payload,step4_evidence.PER_LEG_LIMIT)
    assert not called


def test_serialization_preflight_rejects_cycles_and_aggregate_utf8_budget():
    cycle=[]; cycle.append(cycle)
    with pytest.raises(ValueError,match="cyclic"): step4_evidence._encode(cycle,step4_evidence.PER_LEG_LIMIT)
    with pytest.raises(ValueError,match="aggregate"): step4_evidence._encode(["x"*8000 for _index in range(5)],step4_evidence.PER_LEG_LIMIT)


def _mutate_lifecycle(mutation,npm,composer):
    if mutation=="lifecycle_extra": npm["extra"]=1
    elif mutation=="identity_extra": npm["identity"]["extra"]=1
    elif mutation=="identity_profile": npm["identity"]["profile_id"]="plugin-phpunit-12.5.31"
    elif mutation=="identity_observed": npm["identity"]["package_observed_image_id"]="sha256:"+"5"*64
    elif mutation=="identity_container": npm["identity"]["package_container_id"]="8"*63
    elif mutation=="event_key": npm["resource_events"][0]["extra"]=1
    elif mutation=="event_kind": npm["resource_events"][0]["kind"]="volume"
    elif mutation=="event_state": npm["resource_events"][0]["state"]="running"
    elif mutation=="resource_missing": npm["resource_events"]=[item for item in npm["resource_events"] if item["kind"]!="lease"]
    elif mutation=="resource_terminal": npm["resource_events"][-1]["state"]="attached"
    elif mutation=="detached_only": npm["resource_events"].pop()
    elif mutation=="resurrection": npm["resource_events"].extend([{"kind":"container","name":npm["resource_events"][0]["name"],"state":"created"},{"kind":"container","name":npm["resource_events"][0]["name"],"state":"removed"}])
    elif mutation=="cross_token": npm["resource_events"][1]["name"]="wp-acquire-proxy-"+"b"*16
    elif mutation=="network_no_detach": npm["resource_events"].pop(10)
    elif mutation=="retained": npm["resource_events"][-1]["state"]="retained"
    elif mutation=="runner_mismatch":
        profile=step4_evidence.dependency_egress_proxy.ACQUISITION_PROFILES["plugin-phpunit-12.5.31"]; inventory=step4_evidence.runtime_image_provision.inventory()["images"]
        composer["identity"].update(runner_arch="arm64",package_image_ref=f"composer@{profile.arm64_digest}",proxy_image_ref=f"python@{inventory['python']['arm64']}")
    elif mutation=="same_run_token":
        for item in composer["resource_events"]: item["name"]=item["name"].replace("b"*16,"a"*16)
    elif mutation=="global_id_collision": composer["identity"]["package_container_id"]=npm["identity"]["package_container_id"]
    elif mutation=="proxy_identity_cross": composer["identity"]["proxy_local_image_id"]="sha256:"+"5"*64; composer["identity"]["proxy_observed_image_id"]="sha256:"+"5"*64
    elif mutation=="e2e_duration": npm["timings_seconds"]["end_to_end"]=3
    elif mutation=="sum_duration": npm["timings_seconds"]["end_to_end"]=1.1; composer["timings_seconds"]["end_to_end"]=1.1
    if mutation in {"event_key","event_kind","event_state","resource_missing","resource_terminal","detached_only","resurrection","cross_token","network_no_detach","retained"}:
        npm["cleanup_events"]=[item for item in npm["resource_events"] if item.get("state") in {"removed","detached","retained"}]


def _mutate_numeric(mutation,npm):
    if mutation=="timing_extra": npm["timings_seconds"]["extra"]=0
    elif mutation=="timing_negative": npm["timings_seconds"]["generated"]=-1
    elif mutation=="phase_zero": npm["timings_seconds"]["generated"]=0
    elif mutation=="cleanup_zero": npm["timings_seconds"]["cleanup"]=0
    elif mutation=="end_zero": npm["timings_seconds"]["end_to_end"]=0
    elif mutation=="phase_over_e2e": npm["timings_seconds"]["generated"]=1.1
    elif mutation=="phase_sum": npm["timings_seconds"]["end_to_end"]=0.7
    elif mutation=="metric_extra": npm["metrics"]["extra"]=0
    elif mutation=="metric_bool": npm["metrics"]["mem_available"]=True
    elif mutation=="mem_zero": npm["metrics"]["mem_available"]=0
    elif mutation=="mem_below_admission": npm["metrics"]["mem_available"]=npm["identity"]["admission_required_bytes"]-1
    elif mutation=="proxy_peak_zero": npm["metrics"]["proxy_memory_peak"]=0
    elif mutation=="proxy_over_limit": npm["metrics"]["proxy_memory_peak"]=npm["identity"]["proxy_memory_limit_bytes"]+1
    elif mutation=="package_pre_peak_zero": npm["metrics"]["package_memory_peak_pre_export"]=0
    elif mutation=="package_peak_zero": npm["metrics"]["package_memory_peak"]=0
    elif mutation=="package_pre_over": npm["metrics"]["package_memory_peak_pre_export"]=npm["identity"]["package_memory_limit_bytes"]+1; npm["metrics"]["package_memory_peak"]=npm["metrics"]["package_memory_peak_pre_export"]
    elif mutation=="package_over": npm["metrics"]["package_memory_peak"]=npm["identity"]["package_memory_limit_bytes"]+1
    elif mutation=="workspace_pre_zero": npm["metrics"]["workspace_bytes_used_pre_export"]=0
    elif mutation=="workspace_zero": npm["metrics"]["workspace_bytes_used"]=0
    elif mutation=="workspace_pre_over": npm["metrics"]["workspace_bytes_used_pre_export"]=npm["identity"]["workspace_limit_bytes"]+1
    elif mutation=="workspace_over": npm["metrics"]["workspace_bytes_used"]=npm["identity"]["workspace_limit_bytes"]+1
    elif mutation=="peak_regression": npm["metrics"]["package_memory_peak_pre_export"]=npm["metrics"]["package_memory_peak"]+1
    elif mutation=="limit_mismatch": npm["identity"]["package_memory_limit_bytes"]-=1
    elif mutation=="admission_mismatch": npm["identity"]["admission_required_bytes"]-=1


def _mutate_controlled(mutation,connect):
    internal=connect["topology"]["networks"]["internal"]["name"]; egress=connect["topology"]["networks"]["egress"]["name"]
    if mutation=="controlled_extra": connect["topology"]["extra"]={}
    elif mutation=="duplicate_id": connect["topology"]["networks"]["egress"]["id"]="1"*64
    elif mutation=="duplicate_name": connect["topology"]["networks"]["egress"]["name"]="internal"
    elif mutation=="duplicate_ip": connect["topology"]["containers"]["proxy"]["ips"][internal]="172.20.0.2"
    elif mutation=="public_internal": connect["topology"]["containers"]["package"]["ips"][internal]="8.8.8.8"
    elif mutation=="network_endpoint": connect["topology"]["containers"]["package"]["ips"][internal]="172.20.0.0"
    elif mutation=="broadcast_endpoint": connect["topology"]["containers"]["package"]["ips"][internal]="172.20.255.255"
    elif mutation=="gateway_endpoint": connect["topology"]["containers"]["package"]["ips"][internal]="172.20.0.1"
    elif mutation=="ipv6_endpoint": connect["topology"]["containers"]["package"]["ips"][internal]="fd00::2"
    elif mutation=="fake_subnet": connect["topology"]["networks"]["egress"]["subnet"]="93.184.217.0/28"
    elif mutation=="registry_ip": connect["topology"]["containers"]["registry"]["ips"][egress]="93.184.216.36"
    elif mutation=="bad_control": connect["proxy_status"]["accepted"]=2
    elif mutation=="control_cleanup": connect["cleanup_disposition"]["complete"]=False; connect["cleanup_disposition"]["retained"]=["proxy"]
    elif mutation=="cleanup_one": connect["cleanup_disposition"]["complete"]=1
    elif mutation=="cleanup_inventory": connect["cleanup_disposition"]["removed"]["containers"]["proxy"]["id"]="f"*64
    elif mutation=="controlled_name": connect["topology"]["containers"]["proxy"]["name"]="wp-fake-proxy-"+"c"*12; connect["cleanup_disposition"]["removed"]["containers"]["proxy"]["name"]=connect["topology"]["containers"]["proxy"]["name"]
    elif mutation=="controlled_cross_token": connect["topology"]["containers"]["proxy"]["name"]="wp-proxy-fake-"+"d"*12; connect["cleanup_disposition"]["removed"]["containers"]["proxy"]["name"]=connect["topology"]["containers"]["proxy"]["name"]


def mutate(mutation,npm,composer,connect):
    _mutate_lifecycle(mutation,npm,composer); _mutate_numeric(mutation,npm); _mutate_controlled(mutation,connect)


@pytest.mark.parametrize("mutation", ["missing","extra","failed_pytest","pytest_false","pytest_float","duration_bool","duration_zero","schema_bool","schema_float","wrong_sha","lifecycle_extra","identity_extra","identity_profile","identity_observed","identity_container","timing_extra","timing_negative","phase_zero","cleanup_zero","end_zero","phase_over_e2e","phase_sum","metric_extra","metric_bool","mem_zero","mem_below_admission","proxy_peak_zero","proxy_over_limit","package_pre_peak_zero","package_peak_zero","package_pre_over","package_over","workspace_pre_zero","workspace_zero","workspace_pre_over","workspace_over","peak_regression","limit_mismatch","admission_mismatch","event_key","event_kind","event_state","resource_missing","resource_terminal","detached_only","resurrection","cross_token","network_no_detach","retained","controlled_extra","duplicate_id","duplicate_name","duplicate_ip","public_internal","network_endpoint","broadcast_endpoint","gateway_endpoint","ipv6_endpoint","fake_subnet","registry_ip","bad_control","control_cleanup","cleanup_one","cleanup_inventory","runner_mismatch","same_run_token","global_id_collision","proxy_identity_cross","controlled_name","controlled_cross_token","e2e_duration","sum_duration"])
def test_combiner_rejects_incomplete_or_failed_evidence(tmp_path, mutation):
    evidence = tmp_path / "legs"; evidence.mkdir()
    npm = lifecycle(); composer = lifecycle("plugin-phpunit-12.5.31"); connect = controlled()
    mutate(mutation,npm,composer,connect)
    for leg, payload in (("npm_lifecycle", npm), ("composer_lifecycle", composer), ("controlled_connect", connect)):
        if not (mutation == "missing" and leg == "controlled_connect"): step4_evidence.write_leg(leg, payload, evidence, SHA)
    if mutation in {"schema_bool","schema_float"}:
        path=evidence/"npm_lifecycle.json"; record=json.loads(path.read_text()); record["schema_version"]=True if mutation=="schema_bool" else 1.0; path.write_text(json.dumps(record))
    if mutation == "extra": (evidence / "extra.json").write_text("{}")
    sha = "b" * 40 if mutation == "wrong_sha" else SHA
    status = {"failed_pytest":1,"pytest_false":False,"pytest_float":0.0}.get(mutation,0)
    duration = True if mutation == "duration_bool" else 0 if mutation=="duration_zero" else 1
    with pytest.raises(ValueError): step4_evidence.combine_records(evidence, tmp_path / "combined.json", sha, status, duration)
