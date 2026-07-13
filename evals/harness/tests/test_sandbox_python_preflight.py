import ast
import copy
import errno
import json
import os
import signal
import subprocess
import sys
import time
import uuid

import pytest

import runtime_image_provision as provision
import sandbox_python_preflight as preflight


IMAGE = "python@sha256:" + "a" * 64
IMAGE_ID = "sha256:" + "b" * 64
NETWORK_ID = "c" * 64
CONTAINER_ID = "d" * 64
USER = f"{os.getuid()}:{os.getgid()}"


class Ledger:
    def __init__(self):
        self.events = []

    def record(self, kind, name, state):
        self.events.append((kind, name, state))


def network():
    return [{"Name": "none", "Driver": "null", "Scope": "local", "Id": NETWORK_ID}]


def none_endpoint(post=False):
    return {
        "IPAMConfig": None, "Links": None, "Aliases": None, "MacAddress": "",
        "NetworkID": NETWORK_ID if post else "", "EndpointID": "", "Gateway": "",
        "IPAddress": "", "IPPrefixLen": 0, "IPv6Gateway": "",
        "GlobalIPv6Address": "", "GlobalIPv6PrefixLen": 0, "DriverOpts": None, "DNSNames": None,
    }


def inspect_data(post=False):
    return {
        "Image": IMAGE_ID,
        "Mounts": [],
        "Config": {
            "Image": IMAGE, "User": USER, "Entrypoint": ["/usr/bin/env"],
            "Cmd": ["-i", preflight.PYTHON, "-I", "-S", "-c", preflight.PREFLIGHT_PROBE],
            "WorkingDir": "", "AttachStdin": False, "AttachStdout": True,
            "AttachStderr": True, "Tty": False, "OpenStdin": False, "StdinOnce": False,
            "Env": list(preflight.ENV),
        },
        "HostConfig": {
            "NetworkMode": "none", "ReadonlyRootfs": True, "CapDrop": ["ALL"],
            "CapAdd": None, "GroupAdd": None, "SecurityOpt": ["no-new-privileges:true"],
            "Privileged": False, "AutoRemove": False, "PidsLimit": 16,
            "Memory": 67108864, "MemorySwap": 67108864, "NanoCpus": 250000000,
            "Ulimits": [{"Name": "nofile", "Hard": 64, "Soft": 64}],
            "LogConfig": {"Type": "none", "Config": {}},
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "IpcMode": "private", "CgroupnsMode": "private", "PidMode": "", "UTSMode": "",
            "UsernsMode": "", "Binds": None, "Tmpfs": None, "Devices": [],
            "DeviceRequests": None, "DeviceCgroupRules": None, "PortBindings": {},
            "ExtraHosts": None, "Links": None, "Dns": [], "DnsSearch": [], "DnsOptions": [],
            "Init": None, "ShmSize": 1048576,
        },
        "NetworkSettings": {"Networks": {"none": none_endpoint(post)}},
        "State": {"Status": "exited" if post else "created", "Running": False, "ExitCode": 0, "OOMKilled": False, "Error": ""},
    }


def payload(uid=os.getuid(), gid=os.getgid()):
    value = {
        "capabilities": {"os_getgid": True, "os_getuid": True, "os_kill": True},
        "environment": {"LC_CTYPE": "C.UTF-8"},
        "flags": {"ignore_environment": 1, "isolated": 1, "no_site": 1, "no_user_site": 1, "safe_path": True},
        "gid": gid, "os_name": "posix", "proc_self_exe": preflight.PYTHON_EXE,
        "schema": "wp-proxy-python-preflight.v1", "signals": {"KILL": 9, "TERM": 15},
        "sys_executable": preflight.PYTHON, "sys_platform": "linux", "uid": uid,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def empty_container_list():
    return {"returncode": 0, "stdout": "", "stderr": ""}


def listed_container(name, container_id=CONTAINER_ID):
    return {
        "returncode": 0,
        "stdout": f"{json.dumps(container_id)} {json.dumps(name)}\n",
        "stderr": "",
    }


def test_probe_and_signal_helper_are_constant_minimal_import_programs():
    imports=lambda source:{alias.name for node in ast.walk(ast.parse(source)) if isinstance(node,ast.Import) for alias in node.names}
    assert imports(preflight.PREFLIGHT_PROBE) == {"json", "os", "signal", "sys"}
    assert imports(preflight.SIGNAL_HELPER) == {"os", "signal", "sys"}
    assert "/usr/bin/kill" not in preflight.SIGNAL_HELPER and "shell" not in preflight.SIGNAL_HELPER
    assert "os.kill(i,m[n])" in preflight.SIGNAL_HELPER


@pytest.mark.parametrize("args", [[], [""], ["01", "TERM"], ["+2", "TERM"], ["-2", "TERM"], ["1", "TERM"], ["2147483648", "TERM"], ["2", "HUP"], ["2", "TERM", "extra"]])
def test_signal_helper_invalid_arguments_exit_64_without_syscall(monkeypatch, args):
    calls = []
    monkeypatch.setattr(os, "kill", lambda *items: calls.append(items))
    monkeypatch.setattr(sys, "argv", ["-c", *args])
    with pytest.raises(SystemExit) as stopped:
        exec(compile(preflight.SIGNAL_HELPER, "<signal-helper>", "exec"), {})
    assert stopped.value.code == 64 and calls == []


@pytest.mark.parametrize("name,number", [("TERM", 15), ("KILL", 9)])
def test_signal_helper_valid_signal_calls_os_kill_exactly_once(monkeypatch, name, number):
    calls = []
    monkeypatch.setattr(os, "kill", lambda *items: calls.append(items))
    monkeypatch.setattr(sys, "argv", ["-c", "27", name])
    exec(compile(preflight.SIGNAL_HELPER, "<signal-helper>", "exec"), {})
    assert calls == [(27, number)]


def test_signal_helper_os_kill_oserror_is_nonzero_and_not_retried(monkeypatch):
    calls=[]
    def fail(*items): calls.append(items); raise OSError("denied")
    monkeypatch.setattr(os,"kill",fail); monkeypatch.setattr(sys,"argv",["-c","27","TERM"])
    with pytest.raises(OSError,match="denied"): exec(compile(preflight.SIGNAL_HELPER,"<signal-helper>","exec"),{})
    assert calls==[(27,15)]


def test_signal_helper_real_oserror_exits_nonzero():
    result=subprocess.run([sys.executable,"-I","-S","-c",preflight.SIGNAL_HELPER,"2147483647","TERM"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
    assert result.returncode!=0 and result.stdout==b""


def test_preflight_command_is_exactly_zero_mount_isolated_and_bounded():
    command = preflight.create_command("wp-proxy-preflight-" + "1" * 16, IMAGE, USER)
    joined = " ".join(command)
    assert command[:2] == ["docker", "create"] and "--pull=never" in command
    assert "--network none" in joined and "--read-only" in command and "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined and f"--user {USER}" in joined
    assert "--pids-limit 16" in joined and "--memory 67108864" in joined and "--memory-swap 67108864" in joined
    assert "--cpus 0.25" in joined and "nofile=64:64" in joined and "--shm-size 1m" in joined
    assert not any(item in command for item in ("--mount", "--volume", "--tmpfs", "--device", "--privileged", "--init"))
    assert command[-6:] == ["-i", preflight.PYTHON, "-I", "-S", "-c", preflight.PREFLIGHT_PROBE]


@pytest.mark.parametrize("entry", [
    "LD_PRELOAD=/tmp/x", "DYLD_INSERT_LIBRARIES=/tmp/x", "PYTHONPATH=/tmp/x",
    "PYTHONHOME=/tmp/x", "PYTHONINSPECT=1", "PYTHONSTARTUP=/tmp/x", "PYTHONWARNINGS=x",
    "PYTHONBREAKPOINT=x", "PYTHONMALLOC=x", "PYTHONHASHSEED=1", "PYTHONCOERCECLOCALE=0",
    "PYTHONUTF8=1", "PYTHONSAFEPATH=1", "PYTHONPLATLIBDIR=x", "PYTHONPYCACHEPREFIX=x",
    "PYTHONNODEBUGRANGES=1", "PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1",
    "PYTHONCASEOK=1", "PYTHONEXECUTABLE=x", "PYTHONUSERBASE=x", "PYTHONIOENCODING=x",
])
def test_image_environment_rejects_every_loader_and_runtime_control(entry):
    with pytest.raises(RuntimeError):
        preflight.assert_image_environment([*preflight.ENV, entry])


def test_image_environment_requires_exact_sequence_values_and_unique_keys():
    preflight.assert_image_environment(list(preflight.ENV))
    for values in (list(reversed(preflight.ENV)), [*preflight.ENV, preflight.ENV[0]], [*preflight.ENV[:-1], "PYTHON_SHA256=changed"]):
        with pytest.raises(RuntimeError):
            preflight.assert_image_environment(values)


def test_strict_probe_schema_rejects_duplicates_nonfinite_drift_and_size():
    assert preflight._canonical_json(payload(), os.getuid(), os.getgid())["schema"].endswith(".v1")
    failures = [
        payload().replace('"uid":' + str(os.getuid()), '"uid":NaN'),
        payload().replace('{"capabilities":', '{"uid":1,"capabilities":'),
        payload().replace('"uid":' + str(os.getuid()), '"extra":1,"uid":' + str(os.getuid())),
        payload().replace('"linux"', '"darwin"'), payload().rstrip("\n"), "x" * 2049 + "\n",
    ]
    for value in failures:
        with pytest.raises(RuntimeError):
            preflight._canonical_json(value, os.getuid(), os.getgid())
    wrong_type=json.loads(payload()); wrong_type["flags"]["safe_path"]=1
    with pytest.raises(RuntimeError):
        preflight._canonical_json(json.dumps(wrong_type,sort_keys=True,separators=(",",":"))+"\n",os.getuid(),os.getgid())


@pytest.mark.parametrize("post", [False, True])
def test_inspect_gate_accepts_only_state_appropriate_none_network_shape(post):
    data = inspect_data(post)
    security = preflight.inspect_gate(data, IMAGE, IMAGE_ID, USER, NETWORK_ID, post)
    assert security == ("no-new-privileges:true",)
    changed = copy.deepcopy(data); changed["NetworkSettings"]["Networks"]["none"]["NetworkID"] = "" if post else NETWORK_ID
    with pytest.raises(RuntimeError, match="none-network"):
        preflight.inspect_gate(changed, IMAGE, IMAGE_ID, USER, NETWORK_ID, post)
    changed = copy.deepcopy(data); changed["Mounts"] = [{"Type": "bind"}]
    with pytest.raises(RuntimeError, match="zero-mount"):
        preflight.inspect_gate(changed, IMAGE, IMAGE_ID, USER, NETWORK_ID, post)


@pytest.mark.parametrize("field,value", [("ReadonlyRootfs", False), ("PidsLimit", 17), ("Memory", 1), ("ShmSize", 67108864), ("Binds", []), ("Tmpfs", {})])
def test_inspect_gate_rejects_confinement_resource_and_mount_drift(field, value):
    data = inspect_data(); data["HostConfig"][field] = value
    with pytest.raises(RuntimeError, match=field):
        preflight.inspect_gate(data, IMAGE, IMAGE_ID, USER, NETWORK_ID)


@pytest.mark.parametrize("surface,mutate", [
    ("local image",lambda data:data.update(Image="sha256:"+"e"*64)),
    ("image reference",lambda data:data["Config"].update(Image="python:latest")),
    ("user",lambda data:data["Config"].update(User="1000:1000")),
    ("entrypoint",lambda data:data["Config"].update(Entrypoint=["python"])),
    ("command",lambda data:data["Config"].update(Cmd=["-c","pass"])),
    ("environment",lambda data:data["Config"].update(Env=[*preflight.ENV,"PYTHONPATH=/tmp"])),
    ("security",lambda data:data["HostConfig"].update(SecurityOpt=[])),
    ("extra endpoint field",lambda data:data["NetworkSettings"]["Networks"]["none"].update(GwPriority=0)),
])
def test_inspect_gate_rejects_exact_image_user_command_environment_and_network_drift(surface,mutate):
    data=inspect_data(); mutate(data)
    with pytest.raises(RuntimeError):
        preflight.inspect_gate(data,IMAGE,IMAGE_ID,USER,NETWORK_ID)


def test_run_rejects_root_before_first_docker_call(monkeypatch):
    calls = []
    monkeypatch.setattr(preflight.os, "getuid", lambda: 0)
    with pytest.raises(RuntimeError, match="root"):
        preflight.run(lambda *items: calls.append(items), IMAGE, IMAGE_ID, "0:0", "1" * 16, Ledger())
    assert calls == []


def test_run_owns_unique_ledger_container_and_first_call_is_none_network(monkeypatch):
    ledger = Ledger(); inspections = [inspect_data(), inspect_data(True)]; calls = []
    class Transport: pass
    monkeypatch.setattr(preflight, "start_attached", lambda command, limit=4096: calls.append(command) or Transport())
    monkeypatch.setattr(preflight, "await_attached", lambda _transport, _deadline: {"returncode": 0, "stdout": payload(), "stderr": ""})
    monkeypatch.setattr(preflight, "cleanup_attached", lambda *_args: [])
    def control(command, timeout):
        calls.append(command); assert timeout > 0
        if command[:4] == ["docker", "network", "inspect", "none"]: return {"returncode": 0, "stdout": json.dumps(network()), "stderr": ""}
        if command[1] == "create": return {"returncode": 0, "stdout": CONTAINER_ID + "\n", "stderr": ""}
        if command[:2] == ["docker", "inspect"] and command[2].startswith("wp-proxy-preflight-") and inspections: return {"returncode": 0, "stdout": json.dumps([inspections.pop(0)]), "stderr": ""}
        if command[1:3] == ["rm", "-f"]: return {"returncode": 0, "stdout": command[3], "stderr": ""}
        if command[1:3] == ["container", "ls"]: return empty_container_list()
        raise AssertionError(command)
    result = preflight.run(control, IMAGE, IMAGE_ID, USER, "1" * 16, ledger)
    assert calls[0] == ["docker", "network", "inspect", "none"]
    assert result["name"] == "wp-proxy-preflight-" + "1" * 16
    assert ("container", result["name"], "created") in ledger.events and ("container", result["name"], "removed") in ledger.events
    start = next(command for command in calls if command[:3] == ["docker", "start", "-a"])
    assert start == ["docker", "start", "-a", result["name"]]


@pytest.mark.parametrize("create_mode",["malformed","timeout","nonzero-id"])
def test_create_attempt_cleanup_removes_safe_name_and_authenticated_discovered_id(monkeypatch,create_mode):
    ledger=Ledger(); calls=[]; exists=True; name="wp-proxy-preflight-"+"1"*16
    monkeypatch.setattr(preflight,"cleanup_attached",lambda *_args:[])
    def control(command,_timeout):
        nonlocal exists
        calls.append(command)
        if command[:4]==["docker","network","inspect","none"]: return {"returncode":0,"stdout":json.dumps(network()),"stderr":""}
        if command[1]=="create":
            if create_mode=="timeout": raise TimeoutError("lost create response")
            if create_mode=="nonzero-id": return {"returncode":1,"stdout":CONTAINER_ID+"\n","stderr":"daemon error"}
            return {"returncode":0,"stdout":"malformed\n","stderr":""}
        if command[:2]==["docker","inspect"]:
            if exists: return {"returncode":0,"stdout":json.dumps([{"Name":"/"+name,"Id":CONTAINER_ID}]),"stderr":""}
            return {"returncode":1,"stdout":"","stderr":"absent"}
        if command[1:3]==["rm","-f"]: exists=False; return {"returncode":0,"stdout":name,"stderr":""}
        if command[1:3]==["container","ls"]: return empty_container_list()
        raise AssertionError(command)
    with pytest.raises((RuntimeError,TimeoutError)):
        preflight.run(control,IMAGE,IMAGE_ID,USER,"1"*16,ledger)
    assert ["docker","rm","-f",name] in calls
    if create_mode != "nonzero-id": assert ["docker","inspect",name] in calls
    filters=[command[6] for command in calls if command[1:3]==["container","ls"]]
    assert filters==[f"name=^/{name}$",f"id={CONTAINER_ID}"]
    assert ("container",name,"attempted") in ledger.events and ("container",name,"removed") in ledger.events


def test_cleanup_uses_one_retry_and_proves_name_and_id_absent(monkeypatch):
    ledger = Ledger(); calls = []
    monkeypatch.setattr(preflight, "cleanup_attached", lambda *_args: [])
    def control(command, _timeout):
        calls.append(command)
        if command[1:3] == ["rm", "-f"]:
            return {"returncode": 1 if sum(item[1:3] == ["rm", "-f"] for item in calls) == 1 else 0, "stdout": "", "stderr": ""}
        if command[1:3] == ["container", "ls"]: return empty_container_list()
        raise AssertionError(command)
    preflight._remove(control, "wp-proxy-preflight-" + "1" * 16, CONTAINER_ID, ledger, None)
    assert sum(command[1:3] == ["rm", "-f"] for command in calls) == 2
    assert [command[6] for command in calls if command[1:3] == ["container", "ls"]] == ["name=^/wp-proxy-preflight-" + "1" * 16 + "$", "id=" + CONTAINER_ID]


def test_cleanup_distinguishes_canonical_absence_from_daemon_failure(monkeypatch):
    monkeypatch.setattr(preflight, "cleanup_attached", lambda *_args: [])
    name = "wp-proxy-preflight-" + "1" * 16
    for listing, expected in (
        (empty_container_list(), None),
        ({"returncode": 1, "stdout": "", "stderr": "permission denied"}, "absence listing failed"),
        ({"returncode": 0, "stdout": "not-json\n", "stderr": ""}, "listing is malformed"),
    ):
        def control(command, _timeout):
            if command[1:3] == ["rm", "-f"]: return {"returncode": 0, "stdout": "", "stderr": ""}
            if command[1:3] == ["container", "ls"]: return listing
            raise AssertionError(command)
        if expected is None:
            preflight._remove(control, name, CONTAINER_ID, Ledger(), None)
        else:
            with pytest.raises(RuntimeError, match=expected):
                preflight._remove(control, name, CONTAINER_ID, Ledger(), None)


def test_hung_discovery_is_capped_and_safe_name_removal_still_runs(monkeypatch):
    ledger = Ledger(); calls = []; name = "wp-proxy-preflight-" + "1" * 16
    monkeypatch.setattr(preflight, "cleanup_attached", lambda *_args: [])
    def control(command, timeout):
        calls.append((command, timeout))
        if command[:2] == ["docker", "inspect"]: raise TimeoutError("discovery hung")
        if command[1:3] == ["rm", "-f"]: return {"returncode": 0, "stdout": "", "stderr": ""}
        if command[1:3] == ["container", "ls"]: return empty_container_list()
        raise AssertionError(command)
    preflight._remove(control, name, "", ledger, None)
    assert calls[0][0] == ["docker", "inspect", name] and 0 < calls[0][1] <= 2
    assert any(command == ["docker", "rm", "-f", name] for command, _timeout in calls)


def test_original_preflight_failure_and_cleanup_failure_are_both_preserved(monkeypatch):
    ledger=Ledger(); name="wp-proxy-preflight-"+"1"*16; monkeypatch.setattr(preflight,"cleanup_attached",lambda *_args:[])
    def control(command,_timeout):
        if command[:4]==["docker","network","inspect","none"]: return {"returncode":1,"stdout":"[]","stderr":"network failed"}
        if command[1:3]==["container","ls"]: return listed_container(name)
        raise AssertionError(command)
    with pytest.raises(RuntimeError,match="preflight failed.*cleanup also failed.*retained"):
        preflight.run(control,IMAGE,IMAGE_ID,USER,"1"*16,ledger)
    assert any(state.startswith("duration=") for _kind,_name,state in ledger.events)


class LiveProcess:
    pid=9876
    returncode=None
    def poll(self): return None
    def wait(self,timeout): raise subprocess.TimeoutExpired("docker start -a",timeout)


@pytest.mark.parametrize("failure,target",[
    ("first Thread constructor failure",0),
    ("first Thread start failure",1),
    ("second Thread start failure",2),
])
def test_start_attached_failure_reaps_partial_transport(monkeypatch,failure,target):
    processes=[]; threads=[]; calls=0
    real_popen=preflight.subprocess.Popen; real_thread=preflight.threading.Thread
    def launch(*args,**kwargs):
        process=real_popen(*args,**kwargs); processes.append(process); return process
    def construct(*args,**kwargs):
        nonlocal calls
        calls+=1
        if target==0: raise RuntimeError(failure)
        thread=real_thread(*args,**kwargs); threads.append(thread)
        if calls==target:
            thread.start=lambda:(_ for _ in ()).throw(RuntimeError(failure))
        return thread
    monkeypatch.setattr(preflight.subprocess,"Popen",launch)
    monkeypatch.setattr(preflight.threading,"Thread",construct)
    started=time.monotonic()
    with pytest.raises(RuntimeError,match=failure):
        preflight.start_attached(["/bin/sh","-c","sleep 30"])
    assert time.monotonic()-started<3 and len(processes)==1
    process=processes[0]; assert process.poll() is not None
    with pytest.raises(ProcessLookupError): os.killpg(process.pid,0)
    assert process.stdout.closed and process.stderr.closed
    assert all(not thread.is_alive() for thread in threads)


def test_start_attached_preserves_original_and_cleanup_failures(monkeypatch):
    process=type("Process",(),{"stdout":Stream(),"stderr":Stream()})()
    monkeypatch.setattr(preflight.subprocess,"Popen",lambda *_args,**_kwargs:process)
    monkeypatch.setattr(preflight.threading,"Thread",lambda *_args,**_kwargs:(_ for _ in ()).throw(RuntimeError("constructor failed")))
    monkeypatch.setattr(preflight,"cleanup_attached",lambda *_args:["host process group"])
    with pytest.raises(RuntimeError,match="constructor failed.*cleanup also failed.*host process group"):
        preflight.start_attached(["ignored"])


class Stream:
    def __init__(self): self.closed=False
    def close(self): self.closed=True


class LiveThread:
    def __init__(self): self.joined=[]
    def join(self,timeout): self.joined.append(timeout)
    def is_alive(self): return True


class CompletingThread(LiveThread):
    def __init__(self): super().__init__(); self.alive=True
    def join(self,timeout): super().join(timeout); self.alive=False
    def is_alive(self): return self.alive


def test_expired_attached_cleanup_issues_term_then_kill_without_blocking(monkeypatch):
    process=LiveProcess(); streams=(Stream(),Stream()); threads=(LiveThread(),LiveThread()); calls=[]
    transport=preflight.AttachedTransport(process,streams,threads,{"stdout":bytearray(),"stderr":bytearray()},[])
    monkeypatch.setattr(preflight,"_group_alive",lambda _pid:True)
    monkeypatch.setattr(preflight.os,"killpg",lambda pid,sig:calls.append((pid,sig)))
    failures=preflight.cleanup_attached(transport,time.monotonic()-1)
    assert calls==[(process.pid,15),(process.pid,9)] and "host process group" in failures and "drain thread" in failures
    assert not any(stream.closed for stream in streams) and not any(thread.joined for thread in threads)


def test_exited_main_with_live_group_is_termed_killed_and_proved_absent(monkeypatch):
    process=type("Exited",(),{"pid":4321,"poll":lambda self:0})()
    streams=(Stream(),Stream()); threads=(CompletingThread(),CompletingThread()); calls=[]; waits=iter((True,False))
    transport=preflight.AttachedTransport(process,streams,threads,{"stdout":bytearray(),"stderr":bytearray()},[])
    monkeypatch.setattr(preflight,"_group_alive",lambda _pid:True)
    monkeypatch.setattr(preflight,"_wait_group",lambda _pid,_deadline:next(waits))
    monkeypatch.setattr(preflight.os,"killpg",lambda pid,sig:calls.append((pid,sig)))
    failures=preflight.cleanup_attached(transport,time.monotonic()+1)
    assert calls==[(4321,signal.SIGTERM),(4321,signal.SIGKILL)] and "host process group" not in failures
    assert all(stream.closed for stream in streams) and all(thread.joined for thread in threads)


def test_unexpected_group_probe_error_fails_closed_and_preserves_drain_cleanup(monkeypatch):
    process=type("Exited",(),{"pid":4321,"poll":lambda self:0})()
    streams=(Stream(),Stream()); threads=(LiveThread(),LiveThread())
    transport=preflight.AttachedTransport(process,streams,threads,{"stdout":bytearray(),"stderr":bytearray()},[])
    monkeypatch.setattr(preflight,"_group_alive",lambda _pid:(_ for _ in ()).throw(OSError(errno.EIO,"probe failed")))
    monkeypatch.setattr(preflight.os,"killpg",lambda *_args:None)
    failures=preflight.cleanup_attached(transport,time.monotonic()+0.01)
    assert any("probe OSError" in item for item in failures) and "host process group" in failures
    assert not any(stream.closed for stream in streams) and all(thread.joined for thread in threads)


def docker_ready():
    if not sys.platform.startswith("linux"):
        return False
    try:
        return subprocess.run(
            ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30
        ).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(), reason="Linux Docker boundary unavailable")
def test_docker_zero_mount_python_preflight_exact_native_oracle():
    arch = provision.normalize_arch(subprocess.check_output(["docker", "info", "--format", "{{.Architecture}}"], text=True).strip())
    item = provision.inventory()["images"]["python"]
    image = f"{item['tag'].split(':')[0]}@{item[arch]}"
    evidence = provision.run_capped(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=30, limit=32768)
    assert evidence["returncode"] == 0
    ledger = Ledger()
    result = preflight.run(lambda command, timeout: provision.run_capped(command, timeout=timeout, limit=32768), image, evidence["stdout"].strip(), USER, uuid.uuid4().hex[:16], ledger)
    assert result["duration"] <= preflight.EXECUTION_SECONDS + preflight.CLEANUP_SECONDS
    assert any(event[2] == "removed" for event in ledger.events)
