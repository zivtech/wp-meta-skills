"""Artifact-free provisioning of exact runtime images."""
from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import runtime_image_provision as provision
from wp_runtime_evidence import RuntimeDeadline, scrub_tail

HARNESS = Path(__file__).resolve().parent
RUNTIME_IMAGE_NAMES=("wordpress","wordpress_cli","database","playwright")


@dataclass(frozen=True)
class ProvisionedRuntime:
    images: dict[str, str]
    identities: dict[str, str]
    image_tags: tuple[str, ...]
    provenance: dict


class RuntimeProvisionError(RuntimeError):
    def __init__(self, primary: Exception, cleanup: dict):
        self.primary = primary
        self.cleanup = cleanup
        super().__init__(f"{type(primary).__name__}: trusted runtime provisioning failed")


def _run(command: list[str], timeout: int = 900, deadline:RuntimeDeadline|None=None) -> dict:
    if deadline is not None: timeout=deadline.remaining(timeout)
    result = provision.run_capped(command, timeout=timeout, limit=1048576)
    if result["returncode"]:
        tail = scrub_tail((result.get("stderr") or "") + (result.get("stdout") or ""))
        raise RuntimeError(f"trusted runtime provisioning failed rc={result['returncode']}: {tail}")
    return result


def _verify_inputs(inventory: dict) -> None:
    for relative, expected in inventory["build_inputs"].items():
        actual = hashlib.sha256((HARNESS / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"reviewed runtime build input drift: {relative}")


def _require_isolated_gateway_mode(deadline=None) -> str:
    result=_run(["docker","version","--format","{{.Server.Version}}"],30,deadline)
    version=result["stdout"].strip(); matched=re.fullmatch(r"([0-9]+)\.[0-9]+(?:\.[0-9]+)?[^\s]*",version)
    if not matched or int(matched.group(1))<28:
        raise RuntimeError("generated runtime requires Docker Engine 28+ isolated gateway mode")
    return version


def _pinned_references(inventory: dict, machine: str) -> dict[str, str]:
    result = {}
    for name in RUNTIME_IMAGE_NAMES:
        item=inventory["images"][name]
        repository = item["tag"].split(":")[0]
        result[name] = f"{repository}@{provision.platform_digest(item, machine)}"
    return result


def _verify_tag_provenance(inventory: dict, machine: str, deadline=None) -> None:
    architecture = provision.normalize_arch(machine)
    for name in RUNTIME_IMAGE_NAMES:
        item=inventory["images"][name]
        result = _run(["docker", "buildx", "imagetools", "inspect", item["tag"],
                       "--format", "{{json .Manifest}}"], 300,deadline)
        manifest = json.loads(result["stdout"])
        children = {child.get("platform", {}).get("architecture"): child.get("digest")
                    for child in manifest.get("manifests", [])
                    if child.get("platform", {}).get("os") == "linux"}
        if manifest.get("digest") != item["index"] or children.get(architecture) != item[architecture]:
            raise RuntimeError(f"reviewed runtime tag provenance drift: {name}")


def _pull_pins(references: dict[str, str],deadline=None) -> None:
    for reference in references.values():
        _run(["docker", "pull", reference],deadline=deadline)
        inspected = json.loads(_run(["docker", "image", "inspect", reference], 120,deadline)["stdout"])[0]
        child = reference.rsplit("@", 1)[1]
        if not inspected["Id"].startswith("sha256:") or not any(value.endswith(child) for value in inspected.get("RepoDigests", [])):
            raise RuntimeError(f"pulled runtime image provenance mismatch: {reference}")


def _copy_build_contexts(work: Path, archive: Path, plugin_check:Path) -> tuple[Path, Path, Path]:
    wordpress = work / "wordpress"
    database = work / "database"
    browser = work / "browser"
    shutil.copytree(HARNESS / "runtime-images/wordpress", wordpress)
    shutil.copytree(HARNESS / "runtime-images/database", database)
    shutil.copytree(HARNESS / "runtime-images/browser", browser)
    shutil.copy2(archive, wordpress / archive.name)
    shutil.copy2(plugin_check,wordpress/"plugin-check.zip")
    return wordpress, database, browser


def prepare_build_contexts(work:Path,inventory:dict,deadline=None) -> tuple[Path,Path,Path]:
    archive = work / "wordpress.tar.gz"
    plugin_check=work/"plugin-check.zip"
    core_timeout=deadline.remaining(65) if deadline is not None else 60
    provision.download_core(archive,timeout=core_timeout)
    plugin_timeout=deadline.remaining(65) if deadline is not None else 60
    provision.download_pinned(
        inventory["plugin_check"],plugin_check,timeout=plugin_timeout,maximum=32*1024*1024,
    )
    return _copy_build_contexts(work,archive,plugin_check)


def _build_images(work: Path, references: dict[str, str], inventory: dict,deadline=None) -> tuple[dict, tuple[str, ...]]:
    run_id = hashlib.sha256(str(work).encode()).hexdigest()[:12]
    tags = tuple(f"wp-isolated-{name}:{run_id}" for name in ("wordpress", "database", "browser"))
    wordpress, database, browser = prepare_build_contexts(work,inventory,deadline)
    commands = (
        ["docker", "build", "--network=none", "--pull=false", "-t", tags[0],
         "--build-arg", f"WORDPRESS_BASE={references['wordpress']}",
         "--build-arg", f"CLI_BASE={references['wordpress_cli']}",
         "--build-arg", f"WP_CLI_SHA256={inventory['wp_cli_binary']['sha256']}",
         "--build-arg", f"PLUGIN_CHECK_SHA256={inventory['plugin_check']['sha256']}", str(wordpress)],
        ["docker", "build", "--network=none", "--pull=false", "-t", tags[1],
         "--build-arg", f"DATABASE_BASE={references['database']}", str(database)],
        ["docker", "build", "--pull=false", "-t", tags[2],
         "--build-arg", f"BROWSER_BASE={references['playwright']}", str(browser)],
    )
    try:
        for command in commands: _run(command,deadline=deadline)
        images = {
            name: _run(
                ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
                120, deadline,
            )["stdout"].strip()
            for name, tag in zip(("wordpress", "database", "browser"), tags)
        }
        if any(not value.startswith("sha256:") for value in images.values()):
            raise RuntimeError("trusted runtime build did not return exact local image IDs")
    except Exception as exc:
        raise RuntimeProvisionError(exc, _cleanup_image_tags(tags, deadline)) from exc
    return images, tags


def _identity(image: str, user: str,deadline=None) -> str:
    result = _run(["docker", "run", "--rm", "--entrypoint", "sh", image,
                   "-c", f"id -u {user}; id -g {user}"], 120,deadline)
    values = result["stdout"].splitlines()
    if len(values) != 2 or any(not value.isdigit() or value == "0" for value in values):
        raise RuntimeError(f"runtime image user is not exact and non-root: {user}")
    return ":".join(values)


def provision_runtime(work: Path,deadline:RuntimeDeadline|None=None) -> ProvisionedRuntime:
    inventory = provision.inventory()
    _verify_inputs(inventory)
    engine_version=_require_isolated_gateway_mode(deadline)
    machine = platform.machine()
    _verify_tag_provenance(inventory, machine,deadline)
    references = _pinned_references(inventory, machine)
    _pull_pins(references,deadline)
    images, tags = _build_images(work, references, inventory,deadline)
    try:
        identities = {
            "wordpress": _identity(images["wordpress"], "www-data",deadline),
            "database": _identity(images["database"], "mysql",deadline),
            "browser": _identity(images["browser"], "pwuser",deadline),
        }
    except Exception as exc:
        raise RuntimeProvisionError(exc, _cleanup_image_tags(tags, deadline)) from exc
    return ProvisionedRuntime(images,identities,tags,{
        "pinned_references":references,
        "docker_engine_version":engine_version,
        "plugin_check":{key:inventory["plugin_check"][key] for key in ("version","url","sha256","license")},
    })


def _cleanup_image_tags(tags: tuple[str, ...], deadline:RuntimeDeadline|None=None) -> dict:
    errors=[]
    try:
        timeout=deadline.remaining(120,cleanup=True) if deadline is not None else 120
        removed=provision.run_capped(["docker","image","rm","-f",*tags],timeout=timeout,limit=65536)
    except Exception as exc:
        removed={"returncode":1}; errors.append(f"runtime image removal raised {type(exc).__name__}")
    retained=[]; probe_errors=[]
    for tag in tags:
        try:
            probe_timeout=deadline.remaining(15,cleanup=True) if deadline is not None else 15
            probe=provision.run_capped(
                ["docker","image","inspect","--format","{{.Id}}",tag],
                timeout=probe_timeout,limit=4096,
            )
        except Exception:
            probe_errors.append(f"absence probe failed for {tag}"); retained.append(tag); continue
        if probe["returncode"]==0: retained.append(tag)
        elif "no such image" not in (probe.get("stderr") or "").lower():
            probe_errors.append(f"absence probe failed for {tag}"); retained.append(tag)
    if removed["returncode"] and retained: errors.append("runtime image removal failed")
    errors.extend(probe_errors)
    state="retained" if retained or probe_errors else "removed"
    return {"component":"runtime_images","state":state,"error":"; ".join(errors) or None,
            "remaining":retained,"recovery":[f"docker image rm -f {tag}" for tag in retained]}


def cleanup_images(runtime: ProvisionedRuntime,deadline:RuntimeDeadline|None=None) -> dict:
    return _cleanup_image_tags(runtime.image_tags,deadline)
