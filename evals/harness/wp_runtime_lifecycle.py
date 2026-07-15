"""Create, inspect, execute, and forcibly converge the final runtime."""
from __future__ import annotations

import runtime_image_provision as transport
import wp_runtime_inspection as inspection
import wp_runtime_oracles as oracles
import wp_runtime_topology as topology
from wp_runtime_evidence import RuntimeDeadline, failure_evidence


def _run(command,deadline,cap=120,limit=131072,allow_failure=False):
    result=transport.run_capped(command,timeout=deadline.remaining(cap,cleanup=allow_failure),limit=limit)
    if result["returncode"] and not allow_failure:
        raise RuntimeError(f"isolated Compose command failed rc={result['returncode']}")
    return result


def _ids(kind,project,deadline):
    command=["docker",kind,"ls","-q","--filter",f"label=com.docker.compose.project={project}"]
    result=_run(command,deadline,30,4096,True)
    return result["stdout"].split() if result["returncode"]==0 else ["<probe-failed>"]


def _container_ids(project,deadline):
    result=_run(["docker","ps","-aq","--filter",f"label=com.docker.compose.project={project}"],deadline,30,4096,True)
    return result["stdout"].split() if result["returncode"]==0 else ["<probe-failed>"]


def _safe_probe(probe,errors):
    try:
        return probe()
    except Exception as exc:
        errors.append(failure_evidence(exc)["detail"])
        return ["<probe-failed>"]


def _force_remove(project,deadline):
    containers=_container_ids(project,deadline)
    if containers and containers != ["<probe-failed>"]:
        _run(["docker","rm","-f",*containers],deadline,60,65536,True)
    networks=_ids("network",project,deadline)
    if networks and networks != ["<probe-failed>"]:
        _run(["docker","network","rm",*networks],deadline,60,65536,True)
    volumes=_ids("volume",project,deadline)
    if volumes and volumes != ["<probe-failed>"]:
        _run(["docker","volume","rm","-f",*volumes],deadline,60,65536,True)


def _cleanup(base,project,deadline):
    errors=[]
    try:
        result=_run(base+["down","-v","--remove-orphans","--timeout","10"],deadline,90,65536,True)
        if result["returncode"]: errors.append("compose down failed")
        _force_remove(project,deadline)
    except Exception as exc: errors.append(failure_evidence(exc)["detail"])
    remaining={
        "containers":_safe_probe(lambda:_container_ids(project,deadline),errors),
        "networks":_safe_probe(lambda:_ids("network",project,deadline),errors),
        "volumes":_safe_probe(lambda:_ids("volume",project,deadline),errors),
    }
    retained=any(remaining.values())
    if retained: errors.append("run-owned Docker resources remain")
    recovery=[f"docker ps -aq --filter label=com.docker.compose.project={project} | xargs -r docker rm -f",
              f"docker network ls -q --filter label=com.docker.compose.project={project} | xargs -r docker network rm",
              f"docker volume ls -q --filter label=com.docker.compose.project={project} | xargs -r docker volume rm -f"]
    return {"component":"compose","state":"retained" if retained else "removed",
            "errors":errors,"remaining":remaining,"recovery":recovery if retained else []}


def _primary_status(primary,phase):
    if primary is None: return "pass"
    return "fail" if phase=="oracles" and not isinstance(primary,TimeoutError) else "blocked"


def execute_runtime(
    work,project,runtime,artifact_image,slug,deadline,requested,artifact_digest,
    block_assertion=None,
):
    if not isinstance(deadline,RuntimeDeadline): deadline=RuntimeDeadline.start(deadline)
    compose=work/"compose.json"; spec=topology.write_compose(
        compose,runtime.images,runtime.identities,artifact_image,slug
    )
    base=["docker","compose","-p",project,"-f",str(compose)]
    primary=None; phase="normalize"; evidence={}; checks=()
    try:
        evidence["normalized"]=inspection.inspect_normalized(
            base,runtime.images,runtime.identities,artifact_image,slug,deadline
        )
        phase="create"; _run(base+["create","--pull","never","--no-build"],deadline,180)
        evidence["created"]=inspection.inspect_live(
            base,runtime.images,runtime.identities,artifact_image,project,slug,deadline,
            require_running=False,
        )
        phase="start"; _run(base+["start"],deadline,120)
        evidence["started"]=inspection.inspect_live(
            base,runtime.images,runtime.identities,artifact_image,project,slug,deadline
        )
        phase="oracles"; checks=oracles.run_oracles(
            base,slug,deadline,requested,artifact_digest,block_assertion,
        )
        evidence["post_oracle"]=inspection.inspect_live(
            base,runtime.images,runtime.identities,artifact_image,project,slug,deadline
        )
    except Exception as exc:
        primary=exc
        if isinstance(exc,oracles.OracleFailure): checks=exc.checks
    deadline.begin_cleanup()
    cleanup=_cleanup(base,project,deadline); status=_primary_status(primary,phase)
    if cleanup["state"]!="removed": status="blocked"
    return {"status":status,"primary":failure_evidence(primary) if primary else None,
        "reason":failure_evidence(primary)["detail"] if primary else ("runtime cleanup retained resources" if status=="blocked" else None),
        "checks":checks,"inspection":evidence,"cleanup":cleanup,"spec":spec}
