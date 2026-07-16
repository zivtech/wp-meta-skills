"""Bounded descriptor copies that force exact PHP candidates through tools."""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


MAX_ALIAS_FILES = 64
MAX_ALIAS_FILE_BYTES = 8 * 1024 * 1024
MAX_ALIAS_TOTAL_BYTES = 16 * 1024 * 1024
COPY_BYTES = 64 * 1024
ALIAS_NAME = re.compile(r"^php-[0-9]{4}-[0-9a-f]{16}\.php$")


@dataclass(frozen=True)
class AliasRecord:
    source: Path
    alias_name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class AliasedPhpFiles:
    root: Path
    files: tuple[Path, ...]
    records: tuple[AliasRecord, ...]


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("PHP scanner alias deadline elapsed")


def _copy_verified(source: Path, destination: Path, deadline: float) -> tuple[int, str]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    source_fd = os.open(source, flags)
    destination_fd = None
    digest = hashlib.sha256()
    copied = 0
    try:
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_ALIAS_FILE_BYTES:
            raise ValueError("PHP scanner alias source exceeds its regular-file bound")
        destination_fd = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        while chunk := os.read(source_fd, COPY_BYTES):
            _check_deadline(deadline)
            copied += len(chunk)
            if copied > before.st_size or copied > MAX_ALIAS_FILE_BYTES:
                raise ValueError("PHP scanner alias copy exceeds its file bound")
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                view = view[written:]
            digest.update(chunk)
        after = os.fstat(source_fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size)
        if identity(before) != identity(after) or copied != before.st_size:
            raise ValueError("PHP scanner alias source changed while copying")
        return copied, digest.hexdigest()
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        os.close(source_fd)


def _validated_names(
    files: tuple[Path, ...], alias_names: Mapping[Path, str]
) -> tuple[str, ...]:
    names = []
    for source in files:
        name = alias_names.get(source)
        if not isinstance(name, str) or ALIAS_NAME.fullmatch(name) is None:
            raise ValueError("PHP scanner alias name is missing or invalid")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("PHP scanner alias names collide")
    return tuple(names)


def _expected_member(
    source: Path,
    expected_members: Mapping[Path, tuple[int, str]] | None,
) -> tuple[int, str] | None:
    if expected_members is None:
        return None
    expected = expected_members.get(source)
    valid = (
        isinstance(expected, tuple) and len(expected) == 2
        and isinstance(expected[0], int) and expected[0] >= 0
        and isinstance(expected[1], str) and re.fullmatch(r"[0-9a-f]{64}", expected[1])
    )
    if not valid:
        raise ValueError("PHP scanner alias expected member is missing or invalid")
    return expected


def default_alias_names(files: Iterable[Path]) -> dict[Path, str]:
    return {
        source: f"php-{index:04d}-{hashlib.sha256(str(source).encode()).hexdigest()[:16]}.php"
        for index, source in enumerate(files)
    }


@contextmanager
def stage_aliases(
    files: Iterable[Path],
    alias_names: Mapping[Path, str],
    deadline: float,
    expected_members: Mapping[Path, tuple[int, str]] | None = None,
):
    sources = tuple(files)
    if not sources or len(sources) > MAX_ALIAS_FILES:
        raise ValueError("PHP scanner alias file count exceeds its bound")
    names = _validated_names(sources, alias_names)
    with tempfile.TemporaryDirectory(prefix="wp-php-scanner-alias-") as temporary:
        root = Path(temporary)
        records = []
        total = 0
        for source, name in zip(sources, names, strict=True):
            _check_deadline(deadline)
            size, digest = _copy_verified(source, root / name, deadline)
            expected = _expected_member(source, expected_members)
            if expected is not None and (size, digest) != expected:
                raise ValueError("PHP scanner alias source does not match the bound member")
            total += size
            if total > MAX_ALIAS_TOTAL_BYTES:
                raise ValueError("PHP scanner alias bytes exceed their aggregate bound")
            records.append(AliasRecord(source, name, size, digest))
        yield AliasedPhpFiles(
            root, tuple(root / item.alias_name for item in records), tuple(records)
        )


def remap_output_files(output: dict, aliases: AliasedPhpFiles) -> dict:
    source_by_alias = {
        os.path.abspath(aliases.root / item.alias_name): str(item.source)
        for item in aliases.records
    }
    remapped = {}
    for raw_path, value in (output.get("files") or {}).items():
        reported = Path(raw_path)
        absolute = reported if reported.is_absolute() else aliases.root / reported
        key = source_by_alias.get(os.path.abspath(absolute))
        if key is None:
            raise ValueError("scanner reported a file outside the authenticated alias table")
        remapped[key] = value
    return {**output, "files": remapped}


def evidence(aliases: AliasedPhpFiles, scan_root: Path) -> list[dict]:
    return [
        {
            "source_path": item.source.relative_to(scan_root).as_posix(),
            "alias_name": item.alias_name,
            "size": item.size,
            "sha256": item.sha256,
        }
        for item in aliases.records
    ]
