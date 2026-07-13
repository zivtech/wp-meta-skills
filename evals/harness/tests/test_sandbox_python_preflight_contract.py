import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

import sandbox_python_preflight as preflight


IMAGE="python@sha256:"+"a"*64
IMAGE_ID="sha256:"+"b"*64
NETWORK_ID="c"*64
CONTAINER_ID="d"*64
USER=f"{os.getuid()}:{os.getgid()}"
RUN_ID="1"*16
ENGINE=("28.0.4","28.0.4","1.48","linux","amd64")
DAEMON_ID="daemon-instance-1234567890abcdef"
OTHER_DAEMON_ID="daemon-instance-fedcba0987654321"
PROFILE=(
    ("Binds",True,"null"),("CapAdd",True,"null"),
    ("DeviceCgroupRules",True,"null"),("DeviceRequests",True,"null"),
    ("Devices",True,"empty-array"),("Dns",True,"empty-array"),
    ("DnsOptions",True,"empty-array"),("DnsSearch",True,"empty-array"),
    ("ExtraHosts",True,"null"),("GroupAdd",True,"null"),
    ("Init",False,"missing"),("Links",True,"null"),
    ("PortBindings",True,"empty-object"),("Tmpfs",False,"missing"),
    ("VolumesFrom",True,"null"),
)
PROBE="""import json,os,signal,sys
d={"capabilities":{"os_getgid":callable(os.getgid),"os_getuid":callable(os.getuid),"os_kill":callable(os.kill)},"environment":dict(sorted(os.environ.items())),"flags":{"ignore_environment":sys.flags.ignore_environment,"isolated":sys.flags.isolated,"no_site":sys.flags.no_site,"no_user_site":sys.flags.no_user_site,"safe_path":sys.flags.safe_path},"gid":os.getgid(),"os_name":os.name,"proc_self_exe":os.readlink("/proc/self/exe"),"schema":"wp-proxy-python-preflight.v1","signals":{"KILL":int(signal.SIGKILL),"TERM":int(signal.SIGTERM)},"sys_executable":sys.executable,"sys_platform":sys.platform,"uid":os.getuid()}
sys.stdout.write(json.dumps(d,sort_keys=True,separators=(",",":"),allow_nan=False)+"\\n")
"""

HOST_KEYS=(
    "NetworkMode","ReadonlyRootfs","CapDrop","Privileged","AutoRemove","PidsLimit",
    "Memory","MemorySwap","NanoCpus","Ulimits","LogConfig","RestartPolicy","IpcMode",
    "CgroupnsMode","PidMode","UTSMode","UsernsMode","ShmSize","SecurityOpt",
)
CONFIG_KEYS=(
    "Image","User","Entrypoint","Cmd","WorkingDir","AttachStdin","AttachStdout",
    "AttachStderr","Tty","OpenStdin","StdinOnce","Env",
)
NETWORK_KEYS=(
    "IPAMConfig","Links","Aliases","MacAddress","NetworkID","EndpointID","Gateway",
    "IPAddress","IPPrefixLen","IPv6Gateway","GlobalIPv6Address","GlobalIPv6PrefixLen",
    "DriverOpts","DNSNames","GwPriority",
)
STATE_KEYS=("Status","Running","ExitCode","OOMKilled","Error")


def baseline(post=False):
    endpoint={
        "IPAMConfig":None,"Links":None,"Aliases":None,"MacAddress":"",
        "NetworkID":NETWORK_ID if post else "","EndpointID":"","Gateway":"","IPAddress":"",
        "IPPrefixLen":0,"IPv6Gateway":"","GlobalIPv6Address":"","GlobalIPv6PrefixLen":0,
        "DriverOpts":None,"DNSNames":None,"GwPriority":0,
    }
    host={
        "NetworkMode":"none","ReadonlyRootfs":True,"CapDrop":["ALL"],"Privileged":False,
        "AutoRemove":False,"PidsLimit":16,"Memory":67108864,"MemorySwap":67108864,
        "NanoCpus":250000000,"Ulimits":[{"Name":"nofile","Hard":64,"Soft":64}],
        "LogConfig":{"Type":"none","Config":{}},"RestartPolicy":{"Name":"no","MaximumRetryCount":0},
        "IpcMode":"private","CgroupnsMode":"private","PidMode":"","UTSMode":"","UsernsMode":"",
        "Binds":None,"Devices":[],"PortBindings":{},"ExtraHosts":None,"Links":None,
        "Dns":[],"DnsSearch":[],"DnsOptions":[],"VolumesFrom":None,"ShmSize":1048576,
        "SecurityOpt":["no-new-privileges:true"],"CapAdd":None,"GroupAdd":None,
        "DeviceRequests":None,"DeviceCgroupRules":None,
    }
    config={
        "Image":IMAGE,"User":USER,"Entrypoint":["/usr/bin/env"],
        "Cmd":["-i","/usr/local/bin/python","-I","-S","-c",PROBE],
        "WorkingDir":"","AttachStdin":False,"AttachStdout":True,"AttachStderr":True,
        "Tty":False,"OpenStdin":False,"StdinOnce":False,"Env":[
            "PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305","PYTHON_VERSION=3.13.14",
            "PYTHON_SHA256=639e43243c620a308f968213df9e00f2f8f62332f7adbaa7a7eeb9783057c690",
        ],
    }
    state={"Status":"exited" if post else "created","Running":False,"ExitCode":0,"OOMKilled":False,"Error":""}
    return {"Image":IMAGE_ID,"Mounts":[],"Config":config,"HostConfig":host,"NetworkSettings":{"Networks":{"none":endpoint}},"State":state}


def engine_payload(engine=ENGINE):
    client,server,api,operating_system,architecture=engine
    value={
        "architecture":architecture,"client_version":client,
        "negotiated_api_version":api,"operating_system":operating_system,
        "server_version":server,
    }
    return json.dumps(value,sort_keys=True,separators=(",",":"))+"\n"


def daemon_payload(value=DAEMON_ID):
    return json.dumps(value,separators=(",",":"))+"\n"


@pytest.mark.parametrize("post", [False, True])
def test_independent_baseline_is_accepted_pre_and_post(post):
    preflight.inspect_gate(baseline(post), IMAGE, IMAGE_ID, USER, NETWORK_ID, PROFILE, post)


def wrong(key,value):
    explicit={
        "CapAdd":["SYS_ADMIN"],"GroupAdd":["1"],"DeviceRequests":[],"DeviceCgroupRules":[],
        "Binds":[],"Tmpfs":{},"ExtraHosts":[],"Links":[],"Init":True,
    }
    if key in explicit: return explicit[key]
    if value is None: return "drift"
    if isinstance(value,bool): return not value
    if isinstance(value,int): return value+1
    if isinstance(value,str): return value+"drift"
    if isinstance(value,list): return [*value,"drift"]
    if isinstance(value,dict): return {**value,"drift":True}
    raise AssertionError((key,value))


def mutate(mapping,key,mode):
    if mode=="missing": mapping.pop(key)
    else: mapping[key]=wrong(key,mapping[key])


@pytest.mark.parametrize("mode",["changed","missing"])
@pytest.mark.parametrize("key",HOST_KEYS)
def test_every_host_config_field_is_independently_enforced(key,mode):
    data=baseline(); mutate(data["HostConfig"],key,mode)
    with pytest.raises(RuntimeError): preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID,PROFILE)


@pytest.mark.parametrize("field,present,encoding",PROFILE)
def test_every_optional_host_field_presence_bit_is_independently_enforced(field,present,encoding):
    data=baseline(); host=data["HostConfig"]
    if present: host.pop(field)
    else: host[field]=None
    with pytest.raises(RuntimeError,match=field):
        preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID,PROFILE)


@pytest.mark.parametrize("field,present,encoding",PROFILE)
def test_every_optional_host_field_encoding_is_independently_enforced(field,present,encoding):
    data=baseline(); host=data["HostConfig"]
    alternatives={"missing":False if field=="Init" else {},"null":[],"empty-array":None,"empty-object":None}
    host[field]=alternatives[encoding]
    with pytest.raises(RuntimeError,match=field):
        preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID,PROFILE)


def test_optional_profile_error_redacts_nonempty_value():
    secret="private/path/that/must/not/escape"; data=baseline()
    data["HostConfig"]["Dns"]=[secret]
    with pytest.raises(RuntimeError) as stopped:
        preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID,PROFILE)
    assert secret not in str(stopped.value) and "invalid-redacted" in str(stopped.value)


def test_reviewed_map_is_exact_deep_immutable_and_phase_specific():
    expected={(*ENGINE,"pre_start"):PROFILE,(*ENGINE,"post_exit"):PROFILE}
    assert dict(preflight.REVIEWED_HOSTCONFIG_PROFILES)==expected
    assert all(type(key) is tuple and type(value) is tuple for key,value in expected.items())
    with pytest.raises(TypeError):
        preflight.REVIEWED_HOSTCONFIG_PROFILES[(*ENGINE,"other")]=PROFILE


@pytest.mark.parametrize("mode",["changed","missing"])
@pytest.mark.parametrize("key",CONFIG_KEYS)
def test_every_config_field_is_independently_enforced(key,mode):
    data=baseline(); mutate(data["Config"],key,mode)
    with pytest.raises(RuntimeError): preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID,PROFILE)


@pytest.mark.parametrize("mode",["changed","missing"])
@pytest.mark.parametrize("post",[False,True])
@pytest.mark.parametrize("key",NETWORK_KEYS)
def test_every_none_network_field_is_independently_enforced_pre_and_post(key,post,mode):
    data=baseline(post); endpoint=data["NetworkSettings"]["Networks"]["none"]
    mutate(endpoint,key,mode)
    with pytest.raises(RuntimeError): preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID,PROFILE,post)


@pytest.mark.parametrize("post",[False,True])
@pytest.mark.parametrize("value",[False,"0",-1,1])
def test_gw_priority_requires_exact_integer_zero(post,value):
    data=baseline(post); data["NetworkSettings"]["Networks"]["none"]["GwPriority"]=value
    with pytest.raises(RuntimeError,match="GwPriority|none-network"):
        preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID,PROFILE,post)


@pytest.mark.parametrize("mode",["changed","missing"])
@pytest.mark.parametrize("key",STATE_KEYS)
@pytest.mark.parametrize("post",[False,True])
def test_every_state_field_is_independently_enforced_pre_and_post(key,post,mode):
    data=baseline(post); mutate(data["State"],key,mode)
    with pytest.raises(RuntimeError): preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID,PROFILE,post)


@pytest.mark.parametrize("mode",["changed","missing"])
@pytest.mark.parametrize("surface",["Image","Mounts"])
def test_top_level_image_and_mounts_are_independently_enforced(surface,mode):
    data=baseline()
    if mode=="missing": data.pop(surface)
    else: data[surface]="sha256:"+"e"*64 if surface=="Image" else [{"Type":"bind"}]
    with pytest.raises(RuntimeError): preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID,PROFILE)


def test_production_and_required_workflow_do_not_import_diagnostic_union():
    root=Path(__file__).resolve().parents[3]
    production=(root/"evals/harness/sandbox_python_preflight.py").read_text(encoding="utf-8")
    workflow=(root/".github/workflows/validate.yml").read_text(encoding="utf-8")
    assert "sandbox_python_preflight_diagnostic" not in production
    assert "import sandbox_python_preflight_diagnostic" not in workflow
    assert "Observe exact zero-mount preflight serialization" not in workflow


def probe_payload():
    value={
        "capabilities":{"os_getgid":True,"os_getuid":True,"os_kill":True},"environment":{"LC_CTYPE":"C.UTF-8"},
        "flags":{"ignore_environment":1,"isolated":1,"no_site":1,"no_user_site":1,"safe_path":True},
        "gid":os.getgid(),"os_name":"posix","proc_self_exe":"/usr/local/bin/python3.13",
        "schema":"wp-proxy-python-preflight.v1","signals":{"KILL":9,"TERM":15},
        "sys_executable":"/usr/local/bin/python","sys_platform":"linux","uid":os.getuid(),
    }
    return json.dumps(value,sort_keys=True,separators=(",",":"))+"\n"


class Ledger:
    def __init__(self): self.events=[]
    def record(self,*event): self.events.append(event)


class Clock:
    def __init__(self,expire=""): self.now=100.0; self.calls=0; self.expire=expire; self.deadline=115.0
    def monotonic(self):
        self.calls+=1
        if self.expire=="network" and self.calls==3: self.now=self.deadline
        return self.now
    def spend(self,value=0.25): self.now+=value
    def expire_now(self): self.now=self.deadline


class Scenario:
    def __init__(self,stage="",expire="",cleanup_failure=False,engine=ENGINE):
        self.stage=stage; self.clock=Clock(expire); self.cleanup_failure=cleanup_failure
        self.failed=False; self.exists=False; self.inspections=0; self.rm_attempts=0
        self.execution_timeouts=[]; self.cleanup_timeouts=[]; self.filters=[]
        self.engine=engine; self.engine_calls=0; self.daemon_calls=0; self.commands=[]
        self.daemon_drift=False; self.name_guard_seen=False; self.in_cleanup=False; self.ledger=None
    def result(self,returncode=0,stdout="",stderr=""): return {"returncode":returncode,"stdout":stdout,"stderr":stderr}
    def _record(self,timeout,cleanup=False):
        (self.cleanup_timeouts if cleanup else self.execution_timeouts).append(timeout); self.clock.spend()
    def control(self,command,timeout):
        self.commands.append(command)
        daemon_info=command[:3]==["docker","info","--format"]
        cleanup=self.in_cleanup
        self._record(timeout,cleanup)
        if command[:4]==["docker","network","inspect","none"]:
            if self.stage=="network": self.failed=True; return self.result(7,"[]","network failed")
            if self.clock.expire=="create": self.clock.expire_now()
            return self.result(stdout=json.dumps([{"Name":"none","Driver":"null","Scope":"local","Id":NETWORK_ID}]))
        if command[:3]==["docker","version","--format"]:
            self.engine_calls+=1
            if self.stage=="engine-pre": self.failed=True; return self.result(7,"","version failed")
            if self.stage=="engine-post-fail" and self.engine_calls==2:
                self.failed=True
                return self.result(7,"","version failed")
            observed=self.engine
            if self.stage=="engine-post-drift" and self.engine_calls==2:
                self.failed=True
                observed=(self.engine[0],"28.0.5",*self.engine[2:])
            return self.result(stdout=engine_payload(observed))
        if daemon_info:
            self.daemon_calls+=1
            if self.stage=="daemon-pre-fail" and self.daemon_calls==1:
                return self.result(7,"","daemon identity failed")
            if self.stage=="daemon-pre-bind-drift" and self.engine_calls==1 and not self.exists:
                self.daemon_drift=True
            if self.stage=="daemon-create-drift" and self.exists and self.inspections==0:
                self.daemon_drift=True
            if self.stage=="daemon-post-drift" and self.engine_calls==2 and self.inspections==2:
                self.daemon_drift=True
            if self.stage=="daemon-cleanup-drift" and self.in_cleanup:
                self.daemon_drift=True
            if self.stage=="daemon-between-absence-drift" and self.filters==["name=^/wp-proxy-preflight-"+RUN_ID+"$"]:
                if self.name_guard_seen: self.daemon_drift=True
                else: self.name_guard_seen=True
            if self.stage=="daemon-post-transient" and not self.in_cleanup and self.engine_calls==2 and self.inspections==2:
                return self.result(stdout=daemon_payload(OTHER_DAEMON_ID))
            if self.stage=="daemon-post-transient-fail" and not self.in_cleanup and self.engine_calls==2 and self.inspections==2:
                return self.result(7,"","daemon identity failed")
            observed=OTHER_DAEMON_ID if self.daemon_drift else DAEMON_ID
            return self.result(stdout=daemon_payload(observed))
        if command[1]=="create": return self._create()
        if command[1]=="inspect": return self._inspect()
        if command[1:3]==["rm","-f"]: return self._remove()
        if command[1:3]==["container","ls"]:
            self.filters.append(command[6])
            if self.stage=="daemon-absence-drift": self.daemon_drift=True
            return self.result(9,"","daemon failed") if self.cleanup_failure else self.result()
        raise AssertionError(command)
    def _create(self):
        self.exists=True
        if self.stage=="create-timeout": self.failed=True; raise TimeoutError("create response lost")
        if self.stage=="create-malformed": self.failed=True; return self.result(stdout="malformed\n")
        if self.clock.expire=="pre-inspect": self.clock.expire_now()
        return self.result(stdout=CONTAINER_ID+"\n")
    def _inspect(self):
        if self.failed and self.stage.startswith("create"):
            return self.result(stdout=json.dumps([{"Name":"/wp-proxy-preflight-"+RUN_ID,"Id":CONTAINER_ID}]))
        self.inspections+=1
        phase="pre-inspect" if self.inspections==1 else "post-inspect"
        if self.stage==phase: self.failed=True; return self.result(7,"[]","inspect failed")
        post=self.inspections==2
        if self.clock.expire=="start" and not post: self.clock.expire_now()
        return self.result(stdout=json.dumps([baseline(post)]))
    def _remove(self):
        self.rm_attempts+=1
        if self.rm_attempts==1: return self.result(7,"","retry")
        self.exists=False; return self.result(stdout="removed\n")


def run_case(monkeypatch,scenario):
    class Transport: pass
    monkeypatch.setattr(preflight.time,"monotonic",scenario.clock.monotonic)
    monkeypatch.setattr(preflight,"cleanup_attached",lambda *_args:[])
    def start(_command,limit=4096):
        if scenario.stage=="start": scenario.failed=True; raise OSError("Popen failed")
        if scenario.clock.expire=="await": scenario.clock.expire_now()
        return Transport()
    def await_result(_transport,deadline):
        if scenario.stage=="await": scenario.failed=True; raise TimeoutError("await failed")
        preflight.remaining(deadline)
        if scenario.clock.expire=="post-inspect": scenario.clock.expire_now()
        return {"returncode":0,"stdout":probe_payload(),"stderr":""}
    monkeypatch.setattr(preflight,"start_attached",start); monkeypatch.setattr(preflight,"await_attached",await_result)
    real_remove=preflight._remove
    def remove(*args,**kwargs): scenario.in_cleanup=True; return real_remove(*args,**kwargs)
    monkeypatch.setattr(preflight,"_remove",remove)
    scenario.ledger=Ledger()
    return preflight.run(scenario.control,IMAGE,IMAGE_ID,USER,RUN_ID,scenario.ledger)


def test_strict_engine_tuple_accepts_only_canonical_bounded_json():
    assert preflight._strict_engine(engine_payload())==ENGINE
    invalid=(
        engine_payload().rstrip("\n"),
        engine_payload().replace('"architecture":"amd64"','"architecture":"amd64","architecture":"amd64"'),
        engine_payload().replace('"architecture":"amd64"','"architecture":false'),
        engine_payload().replace('"server_version":"28.0.4"','"server_version":"28.0.4","unexpected":1'),
        "x"*(preflight.ENGINE_LIMIT+1),
    )
    for payload in invalid:
        with pytest.raises(RuntimeError): preflight._strict_engine(payload)


def test_strict_daemon_identity_accepts_only_canonical_bounded_json_string():
    assert preflight._strict_daemon_id(daemon_payload())==DAEMON_ID
    invalid=(
        daemon_payload().rstrip("\n"),json.dumps(False)+"\n",json.dumps("short")+"\n",
        json.dumps("bad identity with spaces")+"\n","x"*(preflight.DAEMON_ID_LIMIT+1),
    )
    for payload in invalid:
        with pytest.raises(RuntimeError): preflight._strict_daemon_id(payload)


@pytest.mark.parametrize("index,value",[(0,"28.0.5"),(1,"28.0.5"),(2,"1.49"),(3,"darwin"),(4,"arm64")])
def test_unknown_engine_coordinate_blocks_before_create(monkeypatch,index,value):
    changed=list(ENGINE); changed[index]=value; scenario=Scenario(engine=tuple(changed))
    with pytest.raises(RuntimeError,match="not reviewed|tuple value drift"): run_case(monkeypatch,scenario)
    assert scenario.engine_calls==1 and scenario.inspections==0 and scenario.rm_attempts==0
    assert not any(command[1]=="create" for command in scenario.commands)
    assert not any(command[:3]==["docker","start","-a"] for command in scenario.commands)


def test_precreate_engine_command_failure_creates_nothing(monkeypatch):
    scenario=Scenario(stage="engine-pre")
    with pytest.raises(RuntimeError,match="engine tuple command failed"): run_case(monkeypatch,scenario)
    assert scenario.engine_calls==1 and scenario.inspections==0 and scenario.rm_attempts==0
    assert not any(command[1]=="create" for command in scenario.commands)


def test_precreate_daemon_identity_failure_creates_nothing(monkeypatch):
    scenario=Scenario(stage="daemon-pre-fail")
    with pytest.raises(RuntimeError,match="daemon identity command failed"): run_case(monkeypatch,scenario)
    assert scenario.daemon_calls==1 and scenario.inspections==0 and scenario.rm_attempts==0
    assert not any(command[1]=="create" for command in scenario.commands)


@pytest.mark.parametrize("stage,created",[("daemon-pre-bind-drift",False),("daemon-create-drift",True)])
def test_daemon_binding_drift_never_reaches_start(monkeypatch,stage,created):
    scenario=Scenario(stage=stage)
    with pytest.raises(RuntimeError,match="daemon identity changed"): run_case(monkeypatch,scenario)
    assert any(command[1]=="create" for command in scenario.commands) is created
    assert not any(command[:3]==["docker","start","-a"] for command in scenario.commands)


def test_missing_post_phase_entry_blocks_before_create(monkeypatch):
    only_pre=MappingProxyType({(*ENGINE,"pre_start"):PROFILE})
    monkeypatch.setattr(preflight,"REVIEWED_HOSTCONFIG_PROFILES",only_pre)
    scenario=Scenario()
    with pytest.raises(RuntimeError,match="not reviewed"): run_case(monkeypatch,scenario)
    assert scenario.engine_calls==1 and scenario.inspections==0 and scenario.rm_attempts==0
    assert not any(command[1]=="create" for command in scenario.commands)


def test_malformed_reviewed_profile_blocks_before_create(monkeypatch):
    malformed=PROFILE[:-1]
    profiles=MappingProxyType({(*ENGINE,"pre_start"):malformed,(*ENGINE,"post_exit"):PROFILE})
    monkeypatch.setattr(preflight,"REVIEWED_HOSTCONFIG_PROFILES",profiles)
    scenario=Scenario()
    with pytest.raises(RuntimeError,match="profile shape drift"): run_case(monkeypatch,scenario)
    assert scenario.engine_calls==1 and scenario.inspections==0 and scenario.rm_attempts==0
    assert not any(command[1]=="create" for command in scenario.commands)


@pytest.mark.parametrize("stage,message",[("engine-post-drift","engine tuple changed"),("engine-post-fail","engine tuple command failed")])
def test_post_exit_engine_reauthentication_failure_cleans_up(monkeypatch,stage,message):
    scenario=Scenario(stage=stage)
    with pytest.raises(RuntimeError,match=message): run_case(monkeypatch,scenario)
    assert scenario.engine_calls==2 and scenario.inspections==2 and scenario.exists is False
    assert scenario.rm_attempts==2 and scenario.filters==[
        "name=^/wp-proxy-preflight-"+RUN_ID+"$","id="+CONTAINER_ID,
    ]
    post_inspect=max(index for index,command in enumerate(scenario.commands) if command[1]=="inspect")
    post_version=max(index for index,command in enumerate(scenario.commands) if command[:3]==["docker","version","--format"])
    assert post_inspect<post_version
    assert scenario.commands[post_version-1][:3]==scenario.commands[post_version+1][:3]==["docker","info","--format"]


@pytest.mark.parametrize("stage",["daemon-post-drift","daemon-cleanup-drift","daemon-absence-drift","daemon-between-absence-drift"])
def test_same_version_daemon_identity_drift_never_false_authenticates_cleanup(monkeypatch,stage):
    scenario=Scenario(stage=stage)
    with pytest.raises(RuntimeError,match="daemon identity changed.*possible retained resource|possible retained resource.*daemon identity changed") as stopped:
        run_case(monkeypatch,scenario)
    states=[state for _kind,_name,state in scenario.ledger.events]
    assert "removed" not in states and "absent" not in states
    assert DAEMON_ID not in str(stopped.value) and OTHER_DAEMON_ID not in str(stopped.value)
    assert DAEMON_ID not in repr(scenario.ledger.events) and OTHER_DAEMON_ID not in repr(scenario.ledger.events)
    if stage=="daemon-cleanup-drift": assert scenario.rm_attempts==0
    if stage in {"daemon-absence-drift","daemon-between-absence-drift"}:
        assert scenario.filters==["name=^/wp-proxy-preflight-"+RUN_ID+"$"]


@pytest.mark.parametrize("stage",["daemon-post-transient","daemon-post-transient-fail"])
def test_observed_transient_daemon_identity_loss_stays_tainted_after_restoration(monkeypatch,stage):
    scenario=Scenario(stage=stage)
    with pytest.raises(RuntimeError,match="cleanup also failed.*previously unverified") as stopped:
        run_case(monkeypatch,scenario)
    states=[state for _kind,_name,state in scenario.ledger.events]
    assert scenario.rm_attempts==2 and scenario.filters==[
        "name=^/wp-proxy-preflight-"+RUN_ID+"$","id="+CONTAINER_ID,
    ]
    assert "removed" not in states and "absent" not in states
    assert DAEMON_ID not in str(stopped.value) and OTHER_DAEMON_ID not in str(stopped.value)


def assert_deadlines(scenario,authenticated):
    assert scenario.execution_timeouts==sorted(scenario.execution_timeouts,reverse=True)
    cleanup=list(scenario.cleanup_timeouts)
    interleaved=[index for index,value in enumerate(cleanup[:-1]) if cleanup[index+1]>value]
    assert len(interleaved)<=1
    if interleaved:
        discovery=cleanup.pop(interleaved[0]); assert discovery<=2
    assert cleanup==sorted(cleanup,reverse=True)
    assert all(0<item<=15 for item in scenario.execution_timeouts)
    assert all(0<item<=10 for item in scenario.cleanup_timeouts)
    assert scenario.rm_attempts<=2
    expected=["name=^/wp-proxy-preflight-"+RUN_ID+"$"]+(["id="+CONTAINER_ID] if authenticated else [])
    assert scenario.filters==expected


@pytest.mark.parametrize("stage",["network","create-malformed","create-timeout","pre-inspect","start","await","post-inspect"])
def test_run_stage_failure_matrix_uses_separate_bounded_cleanup(monkeypatch,stage):
    scenario=Scenario(stage=stage)
    with pytest.raises((RuntimeError,TimeoutError,OSError)): run_case(monkeypatch,scenario)
    assert_deadlines(scenario,stage!="network")


@pytest.mark.parametrize("stage",["network","create","pre-inspect","start","await","post-inspect"])
def test_run_exact_execution_deadline_expiry_at_every_stage(monkeypatch,stage):
    scenario=Scenario(expire=stage)
    with pytest.raises((TimeoutError,RuntimeError)) as stopped: run_case(monkeypatch,scenario)
    chain=[]; current=stopped.value
    while current is not None and current not in chain:
        chain.append(current); current=current.__cause__ or current.__context__
    assert any(isinstance(error,TimeoutError) for error in chain)
    assert_deadlines(scenario,stage not in {"network","create","pre-inspect"})


def test_run_preserves_original_and_canonical_absence_failure(monkeypatch):
    scenario=Scenario(stage="await",cleanup_failure=True)
    with pytest.raises(RuntimeError,match="preflight failed.*await failed.*cleanup also failed.*absence listing failed"):
        run_case(monkeypatch,scenario)
    assert scenario.rm_attempts==2 and scenario.filters==["name=^/wp-proxy-preflight-"+RUN_ID+"$"]
