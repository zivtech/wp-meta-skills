import json
import os

import pytest

import sandbox_python_preflight as preflight
import sandbox_python_preflight_diagnostic as diagnostic


IMAGE="python@sha256:"+"a"*64
IMAGE_ID="sha256:"+"b"*64
NETWORK_ID="c"*64
CONTAINER_ID="d"*64
RUN_ID="1"*16
USER=f"{os.getuid()}:{os.getgid()}"
MISSING=object()


def baseline(tmpfs,post=False):
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
        "Binds":None,"Tmpfs":tmpfs,"Devices":[],"PortBindings":{},"ExtraHosts":None,"Links":None,
        "Dns":[],"DnsSearch":[],"DnsOptions":[],"Init":None,"ShmSize":1048576,
        "SecurityOpt":["no-new-privileges:true"],"CapAdd":None,"GroupAdd":None,
        "DeviceRequests":None,"DeviceCgroupRules":None,
    }
    if tmpfs is MISSING: host.pop("Tmpfs")
    config={
        "Image":IMAGE,"User":USER,"Entrypoint":["/usr/bin/env"],
        "Cmd":["-i",preflight.PYTHON,"-I","-S","-c",preflight.PREFLIGHT_PROBE],
        "WorkingDir":"","AttachStdin":False,"AttachStdout":True,"AttachStderr":True,
        "Tty":False,"OpenStdin":False,"StdinOnce":False,"Env":list(preflight.ENV),
    }
    state={"Status":"exited" if post else "created","Running":False,"ExitCode":0,"OOMKilled":False,"Error":""}
    return {"Image":IMAGE_ID,"Mounts":[],"Config":config,"HostConfig":host,"NetworkSettings":{"Networks":{"none":endpoint}},"State":state}


def probe_payload():
    value={
        "capabilities":{"os_getgid":True,"os_getuid":True,"os_kill":True},"environment":{"LC_CTYPE":"C.UTF-8"},
        "flags":{"ignore_environment":1,"isolated":1,"no_site":1,"no_user_site":1,"safe_path":True},
        "gid":os.getgid(),"os_name":"posix","proc_self_exe":preflight.PYTHON_EXE,
        "schema":"wp-proxy-python-preflight.v1","signals":{"KILL":9,"TERM":15},
        "sys_executable":preflight.PYTHON,"sys_platform":"linux","uid":os.getuid(),
    }
    return json.dumps(value,sort_keys=True,separators=(",",":"))+"\n"


class Ledger:
    def __init__(self): self.events=[]
    def record(self,*event): self.events.append(event)


class Scenario:
    def __init__(self,pre_tmpfs=None,post_tmpfs=None,drift_phase="",retry=False):
        self.pre_tmpfs=pre_tmpfs; self.post_tmpfs=post_tmpfs; self.drift_phase=drift_phase; self.retry=retry
        self.inspections=0; self.rm_attempts=0; self.filters=[]; self.commands=[]
    def result(self,returncode=0,stdout="",stderr=""): return {"returncode":returncode,"stdout":stdout,"stderr":stderr}
    def control(self,command,_timeout):
        self.commands.append(command)
        if command[:4]==["docker","network","inspect","none"]:
            return self.result(stdout=json.dumps([{"Name":"none","Driver":"null","Scope":"local","Id":NETWORK_ID}]))
        if command[:2]==["docker","version"]:
            value={"api_version":"1.52","architecture":"amd64","server_version":"29.4.0"}
            return self.result(stdout=json.dumps(value,sort_keys=True,separators=(",",":"))+"\n")
        if command[1]=="create": return self.result(stdout=CONTAINER_ID+"\n")
        if command[1]=="inspect":
            self.inspections+=1; post=self.inspections==2
            data=baseline(self.post_tmpfs if post else self.pre_tmpfs,post)
            if self.drift_phase==("post" if post else "pre"): data["Config"]["User"]="999:999"
            return self.result(stdout=json.dumps([data]))
        if command[1:3]==["rm","-f"]:
            self.rm_attempts+=1
            if self.retry and self.rm_attempts==1: return self.result(7,stderr="retry")
            return self.result(stdout="removed\n")
        if command[1:3]==["container","ls"]:
            self.filters.append(command[6]); return self.result()
        raise AssertionError(command)


def execute(monkeypatch,scenario):
    monkeypatch.setattr(preflight,"start_attached",lambda *_args:object())
    monkeypatch.setattr(preflight,"await_attached",lambda *_args:{"returncode":0,"stdout":probe_payload(),"stderr":""})
    monkeypatch.setattr(preflight,"cleanup_attached",lambda *_args:[])
    return diagnostic.run(scenario.control,IMAGE,IMAGE_ID,USER,RUN_ID,Ledger())


def assert_cleanup(scenario):
    assert 1<=scenario.rm_attempts<=2
    assert scenario.filters==[
        "name=^/wp-proxy-preflight-"+RUN_ID+"$",
        "id="+CONTAINER_ID,
    ]


def test_diagnostic_returns_only_separate_canonical_sanitized_observations(monkeypatch):
    scenario=Scenario(None,{})
    result=execute(monkeypatch,scenario)
    assert result=={
        "schema":diagnostic.SCHEMA,
        "pre_start":{"api_version":"1.52","architecture":"amd64","server_version":"29.4.0","present":True,"json_type":"null","entry_count":None,"empty":True},
        "post_exit":{"api_version":"1.52","architecture":"amd64","server_version":"29.4.0","present":True,"json_type":"object","entry_count":0,"empty":True,"literal":{}},
    }
    encoded=json.dumps(result,sort_keys=True,separators=(",",":"),allow_nan=False)
    assert json.dumps(json.loads(encoded),sort_keys=True,separators=(",",":"))==encoded
    assert not any(value in encoded for value in ("HostConfig","Config","environment",IMAGE,IMAGE_ID,"/usr/local"))
    create=next(command for command in scenario.commands if command[1]=="create")
    assert create==preflight.create_command("wp-proxy-preflight-"+RUN_ID,IMAGE,USER)
    assert "--network" in create and create[create.index("--network")+1]=="none"
    assert "--mount" not in create and "--tmpfs" not in create
    assert_cleanup(scenario)


@pytest.mark.parametrize("phase",["pre","post"])
@pytest.mark.parametrize("value",[MISSING,{"/tmp":"size=1"},[],"wrong",False])
def test_missing_nonempty_and_wrong_type_tmpfs_fail_closed_and_cleanup(monkeypatch,phase,value):
    scenario=Scenario(value if phase=="pre" else None,value if phase=="post" else None)
    with pytest.raises(RuntimeError,match="Tmpfs serialization") as caught:
        execute(monkeypatch,scenario)
    message=str(caught.value)
    assert ("pre_start" if phase=="pre" else "post_exit") in message
    assert all(field in message for field in ('"present":','"json_type":','"entry_count":','"empty":'))
    assert "/tmp" not in message and "size=1" not in message and "HostConfig" not in message
    assert_cleanup(scenario)


@pytest.mark.parametrize("phase",["pre","post"])
def test_every_other_profile_field_still_uses_exact_gate_and_cleanup(monkeypatch,phase):
    scenario=Scenario(None,{},drift_phase=phase)
    with pytest.raises(RuntimeError,match="Config.User drift"):
        execute(monkeypatch,scenario)
    assert_cleanup(scenario)


def test_diagnostic_uses_ordinary_single_retry_and_name_id_absence(monkeypatch):
    scenario=Scenario(None,{},retry=True)
    result=execute(monkeypatch,scenario)
    assert result["schema"]==diagnostic.SCHEMA
    assert scenario.rm_attempts==2
    assert_cleanup(scenario)
