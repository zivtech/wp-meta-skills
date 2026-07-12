"""Linux-Docker boundary for direct generated package commands."""
from __future__ import annotations
import json, math, os, platform, queue, re, stat, subprocess, threading, time, uuid
from dataclasses import dataclass
from pathlib import Path
import artifact_staging
import runtime_image_provision as provision
import workspace_lease

ENV_ALLOWLIST=frozenset({"HOME","TMPDIR","XDG_CACHE_HOME"})
MAX_WORKSPACE_BYTES=2*1024**3; MAX_WORKSPACE_INODES=200_000; MAX_PIDS=256
MAX_TIMEOUT=900; MAX_STREAM_BYTES=1024*1024; MAX_CPUS=4.0; MAX_MEMORY_BYTES=4*1024**3

def _allowed_images(server_arch):
    inventory=provision.inventory()["images"]; allowed=set()
    for key in ("node","composer"):
        item=inventory[key]; repository=item["tag"].split(":")[0]
        allowed.add(f"{repository}@{item[server_arch]}")
    return frozenset(allowed)

def _normalize_server_arch(value):
    arch={"x86_64":"amd64","amd64":"amd64","aarch64":"arm64","arm64":"arm64"}.get(value.strip().lower())
    if arch is None: raise ValueError("unsupported Docker daemon architecture")
    return arch

def _validate_image(request,server_arch):
    if request.image not in _allowed_images(_normalize_server_arch(server_arch)): raise ValueError("sandbox image is not an approved daemon-platform child")

@dataclass(frozen=True)
class SandboxRequest:
    staged:artifact_staging.StagedTree; image:str; argv:tuple[str,...]
    user:str=f"{os.getuid()}:{os.getgid()}"; environment:tuple[tuple[str,str],...]=()
    workspace_bytes:int=536870912; workspace_inodes:int=50000
    memory:str="1g"; pids:int=128; cpus:str="1.0"; timeout:int=300
    stdout_limit:int=131072; stderr_limit:int=131072; result_parent:Path|None=None

@dataclass(frozen=True)
class SandboxResult:
    status:str; returncode:int|None; stdout:str; stderr:str
    output:artifact_staging.StagedTree|None; detail:str; container_name:str

@dataclass(frozen=True)
class StagedCapability:
    lease_fd:int; root_fd:int; source:str; device:int; inode:int; path_kinds:tuple[tuple[str,str],...]

def _blocked(request,name,detail):
    return SandboxResult("blocked",None,"","",None,detail,name)

def _validate_request(request,retain=False):
    if not request.argv or any(not isinstance(item,str) or "\x00" in item for item in request.argv): raise ValueError("generated argv must be non-empty strings")
    if not re.fullmatch(r"(?:node|composer)@sha256:[0-9a-f]{64}",request.image): raise ValueError("sandbox image is not a canonical digest reference")
    if not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*",request.user): raise ValueError("sandbox user must be canonical numeric non-root")
    keys=[key for key,_value in request.environment]
    if len(keys)!=len(set(keys)) or any(key not in ENV_ALLOWLIST for key in keys): raise ValueError("invalid sandbox environment key")
    if any(not value.isascii() or "\x00" in value or not value.startswith(("/tmp","/home/sandbox","/cache")) for _key,value in request.environment): raise ValueError("invalid sandbox environment value")
    if min(request.workspace_bytes,request.workspace_inodes,request.pids,request.timeout,request.stdout_limit,request.stderr_limit)<=0 or not re.fullmatch(r"[1-9][0-9]*[bkmg]?",request.memory.lower()): raise ValueError("sandbox limits must be positive")
    cpu=float(request.cpus); memory=_memory_bytes(request.memory)
    if not math.isfinite(cpu) or cpu>MAX_CPUS or memory>MAX_MEMORY_BYTES or request.workspace_bytes>MAX_WORKSPACE_BYTES or request.workspace_inodes>MAX_WORKSPACE_INODES or request.pids>MAX_PIDS or request.timeout>MAX_TIMEOUT or max(request.stdout_limit,request.stderr_limit)>MAX_STREAM_BYTES: raise ValueError("sandbox limits exceed reviewed maxima")
    lease=request.staged.lease
    if not isinstance(lease,workspace_lease.WorkspaceLease) or workspace_lease._LIVE_LEASES.get(lease.lease_id) is not lease: raise ValueError("staged tree lease is not live and authentic")
    if request.staged.root.absolute()!=lease.root/"artifact": raise ValueError("staged tree root is outside its live lease")
    if "," in str(request.staged.root): raise ValueError("staged root contains unsupported Docker mount metacharacter")
    lease_fd=artifact_staging._verified_lease_fd(lease); root_fd=None
    try:
        info=os.stat("artifact",dir_fd=lease_fd,follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode): raise ValueError("staged artifact root is not a directory")
        root_fd=os.open("artifact",os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=lease_fd)
        observed=artifact_staging._manifest_from_fd(root_fd,"canonical")
        if observed!=request.staged.manifest: raise ValueError("staged tree manifest is stale")
        opened=os.fstat(root_fd); kinds=tuple(sorted(artifact_staging._filesystem_kinds_from_fd(root_fd).items()))
        capability=StagedCapability(lease_fd,root_fd,f"/proc/{os.getpid()}/fd/{root_fd}",opened.st_dev,opened.st_ino,kinds)
        if retain: return capability
    finally:
        if not retain or 'capability' not in locals():
            if root_fd is not None: os.close(root_fd)
            os.close(lease_fd)

def _create_command(request,name,capability=None):
    work=f"/workspace:size={request.workspace_bytes},nr_inodes={request.workspace_inodes},mode=0700,uid={request.user.split(':')[0]},gid={request.user.split(':')[1]},exec,nosuid,nodev"
    temp=lambda path:f"{path}:size=67108864,nr_inodes=4096,mode=0700,uid={request.user.split(':')[0]},gid={request.user.split(':')[1]},noexec,nosuid,nodev"
    command=["docker","create","--name",name,"--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--user",request.user,"--pids-limit",str(request.pids),"--memory",request.memory,"--memory-swap",request.memory,"--cpus",request.cpus,"--ulimit","nofile=1024:1024","--log-driver","none","--tmpfs",work]
    for path in ("/tmp","/home/sandbox","/cache"): command.extend(("--tmpfs",temp(path)))
    source=capability.source if capability else str(request.staged.root)
    command.extend(("--mount",f"type=bind,src={source},dst=/input,readonly"))
    for key,value in request.environment: command.extend(("--env",f"{key}={value}"))
    command.extend(("--entrypoint","sleep",request.image,"infinity")); return command

def _run(command,request,timeout=None):
    return provision.run_capped(command,timeout=timeout or request.timeout,limit=min(request.stdout_limit,request.stderr_limit))

def _memory_bytes(value):
    units={"b":1,"k":1024,"m":1024**2,"g":1024**3}; suffix=value[-1].lower()
    return int(value[:-1])*units[suffix] if suffix in units else int(value)

def _inspect_boundary(name,request,capability=None):
    result=_run(["docker","inspect",name],request,30)
    if result["returncode"]: raise RuntimeError("container inspection failed")
    data=json.loads(result["stdout"])[0]; host=data["HostConfig"]
    expected_image=_run(["docker","image","inspect",request.image,"--format","{{.Id}}"],request,30)
    if expected_image["returncode"] or data["Image"]!=expected_image["stdout"].strip() or data["Config"]["User"]!=request.user: raise RuntimeError("container image or user drift")
    if data["Config"].get("Entrypoint")!=["sleep"] or data["Config"].get("Cmd")!=["infinity"]: raise RuntimeError("container startup command drift")
    dangerous={"LD_PRELOAD","LD_LIBRARY_PATH","NODE_OPTIONS","PHP_INI_SCAN_DIR"}
    env_keys={item.split("=",1)[0].upper() for item in data["Config"].get("Env",[])}
    if env_keys&dangerous or any(key.endswith("PROXY") for key in env_keys): raise RuntimeError("container inherited dangerous environment")
    if host["NetworkMode"]!="none" or not host["ReadonlyRootfs"] or host["CapDrop"]!=["ALL"]: raise RuntimeError("container isolation drift")
    if host.get("PidMode") or host.get("IpcMode") not in {"","private"} or host.get("UTSMode") or host.get("UsernsMode"): raise RuntimeError("container namespace drift")
    if host.get("RestartPolicy")!={"Name":"no","MaximumRetryCount":0}: raise RuntimeError("container restart drift")
    if host["PidsLimit"]!=request.pids or host["Memory"]!=_memory_bytes(request.memory) or host["MemorySwap"]!=_memory_bytes(request.memory) or host["NanoCpus"]!=int(float(request.cpus)*1_000_000_000): raise RuntimeError("container resource drift")
    if host["SecurityOpt"]!=["no-new-privileges:true"] or host["Binds"] or host["Privileged"]: raise RuntimeError("container security drift")
    if host.get("Devices") or host.get("PortBindings") or host.get("ExtraHosts") or host.get("Dns") or host.get("DnsSearch"): raise RuntimeError("container host surface drift")
    if host.get("Ulimits")!=[{"Name":"nofile","Hard":1024,"Soft":1024}] or host["LogConfig"]["Type"]!="none": raise RuntimeError("container process/logging drift")
    mounts=data["Mounts"]
    expected_source=capability.source if capability else str(request.staged.root)
    if len(mounts)!=1 or mounts[0]["Type"]!="bind" or mounts[0]["Destination"]!="/input" or mounts[0]["RW"] or mounts[0].get("Propagation")!="rprivate" or mounts[0]["Source"]!=expected_source: raise RuntimeError("input bind drift")
    if capability:
        observed=_run(["docker","exec",name,"stat","-c","%d:%i","/input"],request,30)
        if observed["returncode"] or observed["stdout"].strip()!=f"{capability.device}:{capability.inode}": raise RuntimeError("input descriptor identity drift")
    expected={"/workspace","/tmp","/home/sandbox","/cache"}
    if set(host.get("Tmpfs",{}))!=expected: raise RuntimeError("tmpfs inventory drift")
    uid,gid=request.user.split(":")
    work={f"size={request.workspace_bytes}",f"nr_inodes={request.workspace_inodes}","mode=0700",f"uid={uid}",f"gid={gid}","exec","nosuid","nodev"}
    temp={"size=67108864","nr_inodes=4096","mode=0700",f"uid={uid}",f"gid={gid}","noexec","nosuid","nodev"}
    expected_options={"/workspace":work,"/tmp":temp,"/home/sandbox":temp,"/cache":temp}
    if {path:set(options.split(",")) for path,options in host["Tmpfs"].items()}!=expected_options: raise RuntimeError("tmpfs option drift")

def _prepare(name,request,capability):
    copy="cp -R /input/. /workspace/; test -w /workspace; test ! -w /input; test ! -w /; df -Pk /workspace | tail -1; df -Pi /workspace | tail -1"
    result=_run(["docker","exec",name,"sh","-eu","-c",copy],request,60)
    if result["returncode"]: raise RuntimeError("workspace copy or quota probe failed")
    fields=[line.split() for line in result["stdout"].splitlines() if line.strip()]
    if len(fields)!=2 or any(len(line)<3 for line in fields): raise RuntimeError("workspace quota probe missing")
    blocks,inodes=int(fields[0][1]),int(fields[1][1])
    if blocks>(request.workspace_bytes+1023)//1024+1 or inodes>request.workspace_inodes+max(16,request.workspace_inodes//100): raise RuntimeError("workspace quota exceeds request")
    proof=_verify_copy(name,request)
    if proof.manifest!=request.staged.manifest or proof.path_kinds!=capability.path_kinds: raise RuntimeError("workspace copy manifest or graph mismatch")

def _execute(name,request):
    command=["docker","exec","--workdir","/workspace"]
    for key,value in request.environment: command.extend(("--env",f"{key}={value}"))
    environment=["/usr/bin/env","-i","PATH=/usr/local/bin:/usr/bin:/bin"]
    environment.extend(f"{key}={value}" for key,value in request.environment)
    command.extend(("--",name,*environment,*request.argv)); return _run_capped_process(command,request)

def _run_capped_process(command,request):
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env={"PATH":"/usr/bin:/bin"})
    events=queue.Queue(maxsize=32); buffers={"stdout":bytearray(),"stderr":bytearray()}; limits={"stdout":request.stdout_limit,"stderr":request.stderr_limit}; stop=threading.Event()
    def drain(name,stream):
        while not stop.is_set() and (chunk:=stream.read(8192)):
            if len(buffers[name])+len(chunk)>limits[name]: events.put((name,"overflow")); return
            buffers[name].extend(chunk)
        events.put((name,"closed"))
    threads=[threading.Thread(target=drain,args=item,daemon=True) for item in (("stdout",process.stdout),("stderr",process.stderr))]
    for thread in threads: thread.start()
    closed=set(); deadline=time.monotonic()+request.timeout
    try:
        while len(closed)<2:
            remaining=deadline-time.monotonic()
            if remaining<=0: raise TimeoutError("generated command timed out")
            name,event=events.get(timeout=remaining)
            if event=="overflow": raise RuntimeError(f"generated {name} exceeded output limit")
            closed.add(name)
    except (queue.Empty,TimeoutError,RuntimeError) as exc:
        _terminate_process(process)
        if isinstance(exc,queue.Empty): raise TimeoutError("generated command timed out") from exc
        raise
    finally:
        stop.set()
        for stream in (process.stdout,process.stderr): stream.close()
        for thread in threads: thread.join(1)
    if any(thread.is_alive() for thread in threads): _terminate_process(process); raise RuntimeError("generated output drain did not stop")
    remaining=deadline-time.monotonic()
    try: process.wait(timeout=max(0,remaining))
    except subprocess.TimeoutExpired as exc: _terminate_process(process); raise TimeoutError("generated command timed out during reap") from exc
    return {"returncode":process.returncode,"stdout":bytes(buffers["stdout"]).decode("utf-8","replace"),"stderr":bytes(buffers["stderr"]).decode("utf-8","replace")}

def _terminate_process(process):
    if process.poll() is None:
        try: os.killpg(process.pid,9)
        except OSError:
            try: process.kill()
            except OSError: pass
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try: process.kill()
        except OSError: pass
        process.wait()

def _import_output(name,request):
    command=["docker","exec",name,"tar","-C","/workspace","-cf","-","."]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env={"PATH":"/usr/bin:/bin"})
    stderr=bytearray(); overflow=[]
    def drain():
        while chunk:=process.stderr.read(8192):
            if len(stderr)+len(chunk)>request.stderr_limit: overflow.append(True); _terminate_process(process); return
            stderr.extend(chunk)
    thread=threading.Thread(target=drain,daemon=True); thread.start(); timed_out=[]
    def expire(): timed_out.append(True); _terminate_process(process)
    watchdog=threading.Timer(request.timeout,expire); watchdog.start(); output=None
    try:
        bounded_stdout=artifact_staging.BoundedArchiveReader(process.stdout,artifact_staging.MAX_ARCHIVE_STREAM_BYTES)
        output=artifact_staging.import_tar_stream(bounded_stdout,request.result_parent)
        process.wait(); thread.join(1)
        if timed_out or thread.is_alive() or overflow or process.returncode: raise RuntimeError("output archive transport failed")
    except Exception:
        _terminate_process(process); thread.join(1)
        if output is not None: workspace_lease.cleanup(output.lease)
        raise
    finally: watchdog.cancel(); watchdog.join(1)
    return output

def _verify_copy(name,request):
    command=["docker","exec",name,"tar","-C","/workspace","-cf","-","."]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env={"PATH":"/usr/bin:/bin"})
    stderr=bytearray(); overflow=[]; timed_out=[]
    def drain():
        while chunk:=process.stderr.read(8192):
            if len(stderr)+len(chunk)>request.stderr_limit: overflow.append(True); _terminate_process(process); return
            stderr.extend(chunk)
    thread=threading.Thread(target=drain,daemon=True); thread.start()
    watchdog=threading.Timer(request.timeout,lambda:(timed_out.append(True),_terminate_process(process))); watchdog.start()
    try:
        proof=artifact_staging.verify_tar_stream_manifest(process.stdout)
        process.wait(); thread.join(1)
        if timed_out or overflow or thread.is_alive() or process.returncode: raise RuntimeError("workspace proof transport failed")
        return proof
    except Exception: _terminate_process(process); thread.join(1); raise
    finally: watchdog.cancel(); watchdog.join(1)

def _run_live(request,name,capability):
    preflight=_run(["docker","info","--format","{{.Architecture}}"],request,30)
    if preflight["returncode"]: return _blocked(request,name,"Docker is unavailable")
    _validate_image(request,preflight["stdout"])
    created=_run(_create_command(request,name,capability),request,120)
    if created["returncode"]: return _blocked(request,name,"container creation failed")
    started=_run(["docker","start",name],request,60)
    if started["returncode"]: return _blocked(request,name,"container start failed")
    _inspect_boundary(name,request,capability); _prepare(name,request,capability); executed=_execute(name,request)
    if executed["returncode"]: return SandboxResult("fail",executed["returncode"],executed["stdout"],executed["stderr"],None,"generated command failed",name)
    output=_import_output(name,request)
    return SandboxResult("pass",0,executed["stdout"],executed["stderr"],output,"sandbox command passed",name)

def run_sandbox(request:SandboxRequest)->SandboxResult:
    name=f"wp-package-{uuid.uuid4().hex[:16]}"
    try: capability=_validate_request(request,retain=True)
    except Exception as exc: return _blocked(request,name,str(exc))
    if platform.system()!="Linux":
        os.close(capability.root_fd); os.close(capability.lease_fd)
        return _blocked(request,name,"live sandbox requires Linux Docker")
    try: result=_run_live(request,name,capability)
    except Exception as exc: result=_blocked(request,name,f"sandbox boundary failed: {type(exc).__name__}: {exc}")
    finally: os.close(capability.root_fd); os.close(capability.lease_fd)
    try: cleanup=provision.run_capped(["docker","rm","-f",name],timeout=60,limit=32768)
    except Exception as exc:
        try: provision.run_capped(["docker","rm","-f",name],timeout=60,limit=32768)
        except Exception: pass
        if result.output is not None: workspace_lease.cleanup(result.output.lease)
        return _blocked(request,name,f"container cleanup raised {type(exc).__name__}")
    if cleanup["returncode"]:
        try: provision.run_capped(["docker","rm","-f",name],timeout=60,limit=32768)
        except Exception: pass
        if result.output is not None: workspace_lease.cleanup(result.output.lease)
        return _blocked(request,name,"container cleanup failed")
    return result
