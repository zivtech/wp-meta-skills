"""Authenticated PHP alias staging for extension-filtering analyzers."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

import php_scanner_aliases as aliases


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_alias_copy_is_exact_bounded_and_cleaned(tmp_path):
    source = tmp_path / "payload.txt"
    payload = b"<?php echo $_GET['value'];"
    source.write_bytes(payload)
    name = "php-0000-0123456789abcdef.php"
    deadline = time.monotonic() + 10

    with aliases.stage_aliases(
        [source], {source: name}, deadline,
        {source: (len(payload), _digest(payload))},
    ) as staged:
        root = staged.root
        assert staged.files == (root / name,)
        assert staged.files[0].read_bytes() == payload
        assert aliases.evidence(staged, tmp_path) == [{
            "source_path": "payload.txt",
            "alias_name": name,
            "size": len(payload),
            "sha256": _digest(payload),
        }]
        absolute = {str(staged.files[0]): {"messages": []}}
        relative = {name: {"messages": []}}
        assert list(aliases.remap_output_files({"files": absolute}, staged)["files"]) == [str(source)]
        assert list(aliases.remap_output_files({"files": relative}, staged)["files"]) == [str(source)]

    assert not root.exists()


def test_alias_copy_rejects_unbound_content_and_foreign_output(tmp_path):
    source = tmp_path / "bootstrap"
    source.write_bytes(b"<?php")
    name = "php-0000-0123456789abcdef.php"
    with pytest.raises(ValueError, match="bound member"):
        with aliases.stage_aliases(
            [source], {source: name}, time.monotonic() + 10,
            {source: (5, "0" * 64)},
        ):
            pass

    with aliases.stage_aliases(
        [source], {source: name}, time.monotonic() + 10
    ) as staged:
        with pytest.raises(ValueError, match="outside"):
            aliases.remap_output_files(
                {"files": {str(tmp_path / "foreign.php"): {}}}, staged
            )


@pytest.mark.parametrize(
    "names",
    [{}, {Path("payload.txt"): "payload.txt"}],
)
def test_alias_name_contract_is_fail_closed(tmp_path, names):
    source = tmp_path / "payload.txt"
    source.write_bytes(b"<?php")
    mapped = {source: value for _key, value in names.items()}
    with pytest.raises(ValueError, match="name"):
        with aliases.stage_aliases(
            [source], mapped, time.monotonic() + 10
        ):
            pass


def test_alias_deadline_and_file_count_caps_are_fail_closed(tmp_path, monkeypatch):
    source = tmp_path / "payload.txt"
    source.write_bytes(b"<?php")
    name = "php-0000-0123456789abcdef.php"
    with pytest.raises(TimeoutError, match="deadline"):
        with aliases.stage_aliases([source], {source: name}, time.monotonic() - 1):
            pass

    monkeypatch.setattr(aliases, "MAX_ALIAS_FILES", 0)
    with pytest.raises(ValueError, match="count"):
        with aliases.stage_aliases([source], {source: name}, time.monotonic() + 10):
            pass
