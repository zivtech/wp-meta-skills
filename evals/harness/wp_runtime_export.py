"""Capability-derived, mount-free runtime artifact image handoff."""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass

import artifact_staging
import runtime_image_provision as transport
from wp_runtime_evidence import RuntimeBlocked, RuntimeDeadline, docker_absence_proved


@dataclass(frozen=True)
class RuntimeExport:
    image:str
    image_tag:str
    seed_container:str
    manifest:tuple[artifact_staging.ManifestEntry,...]
    digest:str
    evidence:dict


class RuntimeExportCleanupError(RuntimeBlocked):
    def __init__(self,primary,errors,seed,tag):
        self.primary=primary
        self.cleanup={"component":"runtime_artifact_image","state":"retained",
            "error":"; ".join(errors),"resources":{"seed_container":seed,"derived_image":tag},
            "recovery":[f"docker rm -f {seed}",f"docker image rm -f {tag}"]}
        super().__init__(f"{type(primary).__name__}; artifact handoff cleanup failed: {self.cleanup['error']}")


def _run(command,deadline,cap=120,limit=131072,allow_failure=False,stdin=None):
    result=transport.run_capped(command,timeout=deadline.remaining(cap,cleanup=allow_failure),
                                limit=limit,stdin=stdin)
    if result["returncode"] and not allow_failure:
        raise RuntimeBlocked(f"trusted artifact image handoff failed rc={result['returncode']}")
    return result


def _plugin_manifest(manifest,slug):
    prefix=slug+"/"; result=[]
    for item in manifest:
        if not item.path.startswith(prefix): raise ValueError("runtime artifact escaped declared slug")
        result.append(artifact_staging.ManifestEntry(item.path[len(prefix):],item.mode_class,item.size,item.sha256))
    return tuple(result)


def _seed_profile(inspected,base_image,identity):
    host=inspected["HostConfig"]; state=inspected["State"]
    if (inspected["Image"]!=base_image or state.get("Status")!="created" or state.get("Running")
            or host.get("NetworkMode")!="none" or host.get("CapDrop")!=["ALL"]
            or host.get("SecurityOpt")!=["no-new-privileges:true"] or host.get("ReadonlyRootfs") is not False
            or inspected.get("Mounts") or inspected["Config"].get("User")!=identity):
        raise RuntimeBlocked("never-started artifact seed container profile drift")


def _remove_seed(name,deadline):
    _run(["docker","rm","-f",name],deadline,60,65536,True)
    probe=_run(["docker","inspect","--format","{{.Id}}",name],deadline,15,4096,True)
    if probe["returncode"] and not docker_absence_proved(probe,"container"):
        raise RuntimeBlocked("artifact seed absence could not be proved")
    return docker_absence_proved(probe,"container")


def _remove_image(tag,deadline):
    _run(["docker","image","rm","-f",tag],deadline,60,65536,True)
    probe=_run(["docker","image","inspect","--format","{{.Id}}",tag],deadline,15,4096,True)
    if probe["returncode"] and not docker_absence_proved(probe,"image"):
        raise RuntimeBlocked("derived artifact image absence could not be proved")
    return docker_absence_proved(probe,"image")


def _cleanup_failed(seed,tag,deadline):
    errors=[]
    for label,value,remove in (("seed container",seed,_remove_seed),("derived image",tag,_remove_image)):
        if not value: continue
        try:
            if not remove(value,deadline): errors.append(f"{label} retained")
        except Exception as exc: errors.append(f"{label} cleanup {type(exc).__name__}")
    return errors


def _inspect_image(image,deadline):
    return json.loads(_run(["docker","image","inspect",image],deadline,30,131072)["stdout"])[0]


def _config_drift_keys(base, derived):
    keys = sorted(set(base) | set(derived))
    return tuple(key for key in keys if base.get(key) != derived.get(key))


def materialize_export(held,work,slug,runtime,deadline,project):
    suffix=hashlib.sha256((project+slug).encode()).hexdigest()[:12]
    seed=f"{project}-artifact-seed"; tag=f"wp-isolated-artifact:{suffix}"; created=False
    try:
        base=_inspect_image(runtime.images["wordpress"],deadline)
        with tempfile.TemporaryFile(dir=work) as archive:
            manifest=artifact_staging.write_held_tar(held,archive); archive.seek(0)
            _run(["docker","create","--name",seed,"--network","none","--cap-drop","ALL","--security-opt",
                  "no-new-privileges:true",runtime.images["wordpress"]],deadline,60)
            created=True
            inspected=json.loads(_run(["docker","inspect",seed],deadline,30)["stdout"])[0]
            _seed_profile(inspected,runtime.images["wordpress"],base["Config"].get("User"))
            _run(["docker","cp","-",f"{seed}:/var/www/html/wp-content/plugins"],deadline,120,
                 65536,stdin=archive)
        derived=_run(["docker","commit","--pause=false",seed,tag],deadline,120)["stdout"].strip()
        exact=_inspect_image(tag,deadline)
        if exact["Id"] != derived:
            raise RuntimeBlocked("derived artifact image identity drift")
        drift = _config_drift_keys(base["Config"], exact["Config"])
        if drift:
            raise RuntimeBlocked(
                f"derived artifact image WordPress metadata drift fields: {','.join(drift)}"
            )
        if not _remove_seed(seed,deadline): raise RuntimeBlocked("artifact seed container cleanup failed")
        plugin_manifest=_plugin_manifest(manifest,slug)
        evidence={"seed_started":False,"seed_removed":True,"artifact_mounts":0,
                  "base_image":runtime.images["wordpress"],"derived_image":exact["Id"]}
        return RuntimeExport(exact["Id"],tag,seed,plugin_manifest,
                             artifact_staging.digest_manifest_tree(plugin_manifest),evidence)
    except Exception as exc:
        cleanup=_cleanup_failed(seed if created else None,tag,deadline)
        if cleanup: raise RuntimeExportCleanupError(exc,cleanup,seed,tag) from exc
        raise


def seal_export(export,runtime,deadline):
    exact=_inspect_image(export.image_tag,deadline)
    seed=_run(["docker","inspect","--format","{{.Id}}",export.seed_container],deadline,15,4096,True)
    if (exact["Id"]!=export.image
            or not docker_absence_proved(seed,"container")):
        raise RuntimeBlocked("derived artifact image seal drift")
    return {"component":"runtime_artifact_image","state":"sealed",**export.evidence}


def release_export(export,runtime,deadline):
    try: removed=_remove_image(export.image_tag,deadline)
    except Exception as exc:
        return {"component":"runtime_artifact_image","state":"retained","error":type(exc).__name__,
                "recovery":f"docker image rm -f {export.image_tag}"}
    return {"component":"runtime_artifact_image","state":"released" if removed else "retained",
            "error":None if removed else "derived image cleanup failed",
            "recovery":None if removed else f"docker image rm -f {export.image_tag}"}


def prepare_cleanup(_work):
    return {"component":"runtime_artifact_image","state":"not_created","error":None}
