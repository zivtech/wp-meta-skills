"""Typed cleanup and result finalization for generated sandbox outputs."""
from __future__ import annotations

import time
from dataclasses import replace

import artifact_staging
import runtime_image_provision as provision
import sandbox_daemon_control as daemon_control
import sandbox_evidence
import sandbox_none_network


def resource_events(ledger):
    return [
        {"kind":item.kind,"name":item.name,"state":item.state}
        for item in ledger.events
    ] if ledger else []


def staging_cleanup_receipts(error):
    receipts=[]; seen=set(); current=error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current,artifact_staging.StagingCleanupError):
            receipts.append(current.receipt)
        current=current.__cause__ or current.__context__
    return tuple(receipts)


def _merge_receipts(*groups):
    merged=[]
    for group in groups:
        for receipt in group:
            if receipt not in merged: merged.append(receipt)
    return tuple(merged)


def cleanup_successful_output(output,existing=()):
    receipt=artifact_staging.cleanup_staged_tree(output)
    meaningful=receipt.error is not None or receipt.state!="removed"
    merged=_merge_receipts(existing,(receipt,) if meaningful else ())
    return merged,receipt if meaningful else None


def output_cleanup_note(receipt):
    if receipt is None: return ""
    recovery=f"; recovery: {receipt.recovery_path}" if receipt.recovery_path else ""
    error=f" ({receipt.error})" if receipt.error else ""
    return f"; sandbox output cleanup {receipt.state}{error}{recovery}"


def _discard_result_output(result):
    if result.output is None: return result,""
    receipts,receipt=cleanup_successful_output(result.output,result.staging_cleanup_receipts)
    updated=replace(result,output=None,staging_cleanup_receipts=receipts)
    return updated,output_cleanup_note(receipt)


def retry_container_cleanup(target,ledger,deadline):
    control=lambda command,value:provision.run_capped(command,timeout=value,limit=32768)
    try: daemon_control.retry(ledger,["docker","rm","-f",target],control,deadline); return True
    except Exception: return False


def _cleanup_recovery(name,target,retained,ledger):
    if not retained: return "; retry completed"
    identity="; recovery requires the original daemon" if ledger.identity_tainted else ""
    return f"; retained {name}{identity}; recovery: docker rm -f {target}"


def _finalize(result,run_started,ledger,**changes):
    detail=sandbox_evidence.finalize(
        changes.pop("detail",result.detail),end_to_end=time.monotonic()-run_started,
        resources=resource_events(ledger),**changes.pop("evidence",{}),
    )
    return replace(result,detail=detail,**changes)


def cleanup_package_result(result,name,ledger,run_started,retry=retry_container_cleanup):
    states=[item.state for item in ledger.events if item.kind=="container" and item.name==name]
    if not ledger.created("container",name) or states[-1]=="removed":
        return _finalize(result,run_started,ledger)
    started=time.monotonic()
    evidence={"outcome":"blocked","timing":{"cleanup":0.0}}
    if ledger.identity_tainted:
        result,note=_discard_result_output(result); ledger.record("container",name,"retained")
        error=f"Docker identity was tainted; retained {name}; recovery requires the original daemon{note}"
    else:
        deadline=time.monotonic()+90; control=lambda command,value:provision.run_capped(command,timeout=value,limit=32768)
        try: cleanup=daemon_control.run(ledger,["docker","rm","-f",ledger.target(name)],60,control,deadline)
        except sandbox_none_network.DaemonIdentityError as exc:
            result,note=_discard_result_output(result); ledger.record("container",name,"retained")
            error=f"container cleanup identity failed: {exc}; retained {name}; recovery requires the original daemon{note}"
        except Exception as exc:
            target=ledger.target(name); retained=not retry(target,ledger,deadline); ledger.record("container",name,"retained" if retained else "removed")
            result,note=_discard_result_output(result); error=f"container cleanup raised {type(exc).__name__}{_cleanup_recovery(name,target,retained,ledger)}{note}"
        else:
            if not cleanup["returncode"]:
                ledger.record("container",name,"removed")
                return _finalize(result,run_started,ledger,evidence={"timing":{"cleanup":time.monotonic()-started}})
            target=ledger.target(name); retained=not retry(target,ledger,deadline); ledger.record("container",name,"retained" if retained else "removed")
            result,note=_discard_result_output(result); error=f"container cleanup initially failed{_cleanup_recovery(name,target,retained,ledger)}{note}"
    evidence["error"]=error; evidence["timing"]["cleanup"]=time.monotonic()-started
    return _finalize(result,run_started,ledger,status="blocked",returncode=None,output=None,evidence=evidence)
