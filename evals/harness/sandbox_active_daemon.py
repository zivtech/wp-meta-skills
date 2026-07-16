"""Per-context daemon binding for package Docker commands and transports."""
from __future__ import annotations

import contextvars
import time

import runtime_image_provision as provision
import sandbox_daemon_control as daemon_control

_LEDGER=contextvars.ContextVar("wp_sandbox_daemon_ledger",default=None)


def activate(ledger): return _LEDGER.set(ledger)
def reset(token): _LEDGER.reset(token)
def current(): return _LEDGER.get()
def _control(command,timeout): return provision.run_capped(command,timeout=timeout,limit=32768)


def request_run(command,request,timeout):
    ledger=current(); raw=lambda item,value:provision.run_capped(item,timeout=value,limit=min(request.stdout_limit,request.stderr_limit))
    return daemon_control.run(ledger,command,timeout,raw) if ledger else raw(command,timeout)


def _after(ledger,boundary,original=None):
    try: daemon_control.require(ledger,_control,boundary)
    except Exception as identity:
        if original is not None: raise identity from original
        raise


def process(raw,command,request,deadline=None,health_check=None):
    ledger=current()
    if ledger is None: return raw(command,request,deadline=deadline,health_check=health_check)
    boundary=(deadline or time.monotonic()+request.timeout)+60; periodic=daemon_control.periodic(ledger,_control,boundary)
    daemon_control.require(ledger,_control,boundary)
    def health():
        periodic()
        if health_check is not None: health_check()
    try: result=raw(command,request,deadline=deadline,health_check=health)
    except Exception as original:
        _after(ledger,boundary,original); raise
    _after(ledger,boundary); return result


def monitor(deadline=None):
    ledger=current()
    if ledger is None: return None
    boundary=(deadline or time.monotonic()+900)+60
    return daemon_control.periodic(ledger,_control,boundary)


def call(operation,deadline=None,cleanup=None):
    ledger=current()
    if ledger is None: return operation()
    boundary=(deadline or time.monotonic()+900)+60; daemon_control.require(ledger,_control,boundary)
    try: result=operation()
    except Exception as original:
        _after(ledger,boundary,original); raise
    try: _after(ledger,boundary)
    except Exception as identity:
        if cleanup is not None:
            try: cleanup(result)
            except Exception as release: raise RuntimeError(f"daemon identity failed and result cleanup raised {type(release).__name__}") from identity
        raise
    return result
