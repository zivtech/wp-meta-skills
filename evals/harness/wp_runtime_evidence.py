"""Cumulative deadlines and sanitized runtime diagnostics."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

SECRET=re.compile(r"(?i)(authorization|cookie|password|passwd|secret|token|api[_-]?key)(\s*[:=]\s*)([^\s,;]+)")
QUOTED_SECRET=re.compile(
    r'''(?i)(["'](?:authorization|cookie|password|passwd|secret|token|api[_-]?key)["']\s*:\s*["'])([^"']*)(["'])'''
)
URL_CREDENTIAL=re.compile(r"(https?://)[^/@\s]+@")


class RuntimeBlocked(RuntimeError):
    """A prerequisite or containment proof could not be established."""


@dataclass
class RuntimeDeadline:
    end:float
    cleanup_seconds:float=180.0
    cleanup_end:float|None=None

    @classmethod
    def start(cls,seconds:int):
        return cls(time.monotonic()+seconds)

    def remaining(self,cap:float,*,cleanup:bool=False)->float:
        now=time.monotonic()
        if cleanup and self.cleanup_end is None:
            self.cleanup_end=now+self.cleanup_seconds
        boundary=self.cleanup_end if cleanup else self.end
        value=min(cap,boundary-now)
        if value<=0: raise TimeoutError("aggregate runtime deadline exhausted")
        return max(0.1,value)

    def begin_cleanup(self)->None:
        self.cleanup_end=time.monotonic()+self.cleanup_seconds


def scrub_tail(value:str|None,limit:int=2000)->str:
    text=(value or "").replace("\x00","")[-limit:]
    text=QUOTED_SECRET.sub(r"\1[REDACTED]\3",text)
    text=SECRET.sub(lambda match:match.group(1)+match.group(2)+"[REDACTED]",text)
    return URL_CREDENTIAL.sub(r"\1[REDACTED]@",text)


def docker_absence_proved(result: dict, kind: str) -> bool:
    """Accept only Docker's exact not-found diagnostics as absence evidence."""
    if result.get("returncode") == 0:
        return False
    detail = f"{result.get('stderr') or ''}\n{result.get('stdout') or ''}".lower()
    markers = {
        "container": ("no such container", "no such object"),
        "image": ("no such image", "no such object"),
    }
    if kind not in markers:
        raise ValueError(f"unsupported Docker absence kind: {kind}")
    return any(marker in detail for marker in markers[kind])


def failure_evidence(exc:Exception)->dict:
    return {"type":type(exc).__name__,"detail":scrub_tail(str(exc),1000)}
