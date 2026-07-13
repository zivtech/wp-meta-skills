import json
import os

import pytest

import sandbox_python_preflight as preflight


IMAGE="python@sha256:"+"a"*64
IMAGE_ID="sha256:"+"b"*64
NETWORK_ID="c"*64
CONTAINER_ID="d"*64
USER=f"{os.getuid()}:{os.getgid()}"
RUN_ID="1"*16
PROBE="""import json,os,signal,sys
d={"capabilities":{"os_getgid":callable(os.getgid),"os_getuid":callable(os.getuid),"os_kill":callable(os.kill)},"environment":dict(sorted(os.environ.items())),"flags":{"ignore_environment":sys.flags.ignore_environment,"isolated":sys.flags.isolated,"no_site":sys.flags.no_site,"no_user_site":sys.flags.no_user_site,"safe_path":sys.flags.safe_path},"gid":os.getgid(),"os_name":os.name,"proc_self_exe":os.readlink("/proc/self/exe"),"schema":"wp-proxy-python-preflight.v1","signals":{"KILL":int(signal.SIGKILL),"TERM":int(signal.SIGTERM)},"sys_executable":sys.executable,"sys_platform":sys.platform,"uid":os.getuid()}
sys.stdout.write(json.dumps(d,sort_keys=True,separators=(",",":"),allow_nan=False)+"\\n")
"""

HOST_KEYS=(
    "NetworkMode","ReadonlyRootfs","CapDrop","Privileged","AutoRemove","PidsLimit",
    "Memory","MemorySwap","NanoCpus","Ulimits","LogConfig","RestartPolicy","IpcMode",
    "CgroupnsMode","PidMode","UTSMode","UsernsMode","Binds","Tmpfs","Devices",
    "PortBindings","ExtraHosts","Links","Dns","DnsSearch","DnsOptions","Init","ShmSize",
    "SecurityOpt","CapAdd","GroupAdd","DeviceRequests","DeviceCgroupRules",
)
CONFIG_KEYS=(
    "Image","User","Entrypoint","Cmd","WorkingDir","AttachStdin","AttachStdout",
    "AttachStderr","Tty","OpenStdin","StdinOnce","Env",
)
NETWORK_KEYS=(
    "IPAMConfig","Links","Aliases","MacAddress","NetworkID","EndpointID","Gateway",
    "IPAddress","IPPrefixLen","IPv6Gateway","GlobalIPv6Address","GlobalIPv6PrefixLen",
    "DriverOpts","DNSNames",
)
STATE_KEYS=("Status","Running","ExitCode","OOMKilled","Error")


def baseline(post=False):
    endpoint={
        "IPAMConfig":None,"Links":None,"Aliases":None,"MacAddress":"",
        "NetworkID":NETWORK_ID if post else "","EndpointID":"","Gateway":"","IPAddress":"",
        "IPPrefixLen":0,"IPv6Gateway":"","GlobalIPv6Address":"","GlobalIPv6PrefixLen":0,
        "DriverOpts":None,"DNSNames":None,
    }
    host={
        "NetworkMode":"none","ReadonlyRootfs":True,"CapDrop":["ALL"],"Privileged":False,
        "AutoRemove":False,"PidsLimit":16,"Memory":67108864,"MemorySwap":67108864,
        "NanoCpus":250000000,"Ulimits":[{"Name":"nofile","Hard":64,"Soft":64}],
        "LogConfig":{"Type":"none","Config":{}},"RestartPolicy":{"Name":"no","MaximumRetryCount":0},
        "IpcMode":"private","CgroupnsMode":"private","PidMode":"","UTSMode":"","UsernsMode":"",
        "Binds":None,"Tmpfs":None,"Devices":[],"PortBindings":{},"ExtraHosts":None,"Links":None,
        "Dns":[],"DnsSearch":[],"DnsOptions":[],"Init":None,"ShmSize":1048576,
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


@pytest.mark.parametrize("post", [False, True])
def test_independent_baseline_is_accepted_pre_and_post(post):
    preflight.inspect_gate(baseline(post), IMAGE, IMAGE_ID, USER, NETWORK_ID, post)


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
    with pytest.raises(RuntimeError): preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID)


@pytest.mark.parametrize("mode",["changed","missing"])
@pytest.mark.parametrize("key",CONFIG_KEYS)
def test_every_config_field_is_independently_enforced(key,mode):
    data=baseline(); mutate(data["Config"],key,mode)
    with pytest.raises(RuntimeError): preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID)


@pytest.mark.parametrize("mode",["changed","missing"])
@pytest.mark.parametrize("post",[False,True])
@pytest.mark.parametrize("key",NETWORK_KEYS)
def test_every_none_network_field_is_independently_enforced_pre_and_post(key,post,mode):
    data=baseline(post); endpoint=data["NetworkSettings"]["Networks"]["none"]
    mutate(endpoint,key,mode)
    with pytest.raises(RuntimeError): preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID,post)


@pytest.mark.parametrize("mode",["changed","missing"])
@pytest.mark.parametrize("key",STATE_KEYS)
@pytest.mark.parametrize("post",[False,True])
def test_every_state_field_is_independently_enforced_pre_and_post(key,post,mode):
    data=baseline(post); mutate(data["State"],key,mode)
    with pytest.raises(RuntimeError): preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID,post)


@pytest.mark.parametrize("mode",["changed","missing"])
@pytest.mark.parametrize("surface",["Image","Mounts"])
def test_top_level_image_and_mounts_are_independently_enforced(surface,mode):
    data=baseline()
    if mode=="missing": data.pop(surface)
    else: data[surface]="sha256:"+"e"*64 if surface=="Image" else [{"Type":"bind"}]
    with pytest.raises(RuntimeError): preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID)


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
    def __init__(self,stage="",expire="",cleanup_failure=False):
        self.stage=stage; self.clock=Clock(expire); self.cleanup_failure=cleanup_failure
        self.failed=False; self.exists=False; self.inspections=0; self.rm_attempts=0
        self.execution_timeouts=[]; self.cleanup_timeouts=[]; self.filters=[]
    def result(self,returncode=0,stdout="",stderr=""): return {"returncode":returncode,"stdout":stdout,"stderr":stderr}
    def _record(self,timeout,cleanup=False):
        (self.cleanup_timeouts if cleanup else self.execution_timeouts).append(timeout); self.clock.spend()
    def control(self,command,timeout):
        cleanup=command[1:3] in (["rm","-f"],["container","ls"]) or (
            command[1]=="inspect" and (self.failed or not self.exists)
        )
        self._record(timeout,cleanup)
        if command[:4]==["docker","network","inspect","none"]:
            if self.stage=="network": self.failed=True; return self.result(7,"[]","network failed")
            if self.clock.expire=="create": self.clock.expire_now()
            return self.result(stdout=json.dumps([{"Name":"none","Driver":"null","Scope":"local","Id":NETWORK_ID}]))
        if command[1]=="create": return self._create()
        if command[1]=="inspect": return self._inspect()
        if command[1:3]==["rm","-f"]: return self._remove()
        if command[1:3]==["container","ls"]:
            self.filters.append(command[6])
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
    return preflight.run(scenario.control,IMAGE,IMAGE_ID,USER,RUN_ID,Ledger())


def assert_deadlines(scenario,authenticated):
    assert scenario.execution_timeouts==sorted(scenario.execution_timeouts,reverse=True)
    cleanup=list(scenario.cleanup_timeouts)
    if cleanup and cleanup[0]<=2 and cleanup[1:]:
        discovery=cleanup.pop(0)
        assert discovery<=2
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
    with pytest.raises(TimeoutError): run_case(monkeypatch,scenario)
    assert_deadlines(scenario,stage not in {"network","create"})


def test_run_preserves_original_and_canonical_absence_failure(monkeypatch):
    scenario=Scenario(stage="await",cleanup_failure=True)
    with pytest.raises(RuntimeError,match="preflight failed.*await failed.*cleanup also failed.*absence listing failed"):
        run_case(monkeypatch,scenario)
    assert scenario.rm_attempts==2 and scenario.filters==["name=^/wp-proxy-preflight-"+RUN_ID+"$"]
