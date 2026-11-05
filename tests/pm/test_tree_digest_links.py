"""Realized digests bind link text without reading the linked directory, and bind
what pm published rather than what a process later left behind."""
import os
from pathlib import Path

import pytest

from pm.store import digest_matches, tree_digest


def test_digest_without_pathlib_junction_api(tmp_path, monkeypatch):
    # Source updates reach the store before replacing a pre-3.12 interpreter.
    monkeypatch.delattr(Path, "is_junction", raising=False)
    root = tmp_path / "tree"
    nested = root / "lib"
    nested.mkdir(parents=True)
    payload = nested / "payload"
    payload.write_bytes(b"before")
    first = tree_digest(root)
    assert tree_digest(root) == first
    payload.write_bytes(b"after")
    assert tree_digest(root) != first


@pytest.mark.platforms("windows", "posix")
def test_directory_links_bind_only_their_target_text(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "payload").write_bytes(b"unchanged")
    left, right = tmp_path / "left", tmp_path / "right"
    for target in (left, right):
        target.mkdir()
        (target / "content").write_bytes(b"same bytes")
    plain = tree_digest(root)
    link = root / "directory"
    try:
        link.symlink_to(Path("..") / "left", target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("directory symlinks require Windows Developer Mode or privilege")
        raise
    first = tree_digest(root)
    assert first != plain
    (left / "content").write_bytes(b"changed outside the tree")
    assert tree_digest(root) == first
    link.unlink()
    link.symlink_to(Path("..") / "right", target_is_directory=True)
    assert tree_digest(root) != first
    link.unlink()
    link.symlink_to(".", target_is_directory=True)
    cycle = tree_digest(root)
    assert tree_digest(root) == cycle
    assert cycle not in (plain, first)


@pytest.mark.platforms("windows")
def test_junctions_bind_target_text_without_walking_outside(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.delattr(Path, "is_junction", raising=False)
    root = tmp_path / "tree"
    root.mkdir()
    left, right = tmp_path / "left", tmp_path / "right"
    for target in (left, right):
        target.mkdir()
        (target / "content").write_bytes(b"same bytes")
    junction = root / "junction"
    command = str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe")

    def point_at(target):
        result = subprocess.run(
            [command, "/d", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    point_at(left)
    try:
        first = tree_digest(root)
        (left / "content").write_bytes(b"changed outside the tree")
        assert tree_digest(root) == first
        junction.rmdir()
        point_at(right)
        assert tree_digest(root) != first
    finally:
        junction.rmdir()
    assert (left / "content").read_bytes() == b"changed outside the tree"
    assert (right / "content").read_bytes() == b"same bytes"


def test_backend_identity_marker_is_not_payload(tmp_path):
    """A backend writes its identity marker into site-packages after pm published it.

    ``hermes_cli/web_server.py`` drops ``.hermes-ssh-runtime-<nonce>`` into the
    managed interpreter's purelib on boot, and it has to stay inside the venv so a
    replaced venv loses it. The digest is over what pm published, so that marker
    must not read as a payload change.
    """
    root = tmp_path / "entry"
    site = root / "lib" / "python3.14" / "site-packages"
    site.mkdir(parents=True)
    (site / "payload.py").write_bytes(b"published = True\n")
    published = tree_digest(root)

    (site / ".hermes-ssh-runtime-1a2b3c4d5e6f7a8b").write_text("pid=1234\n")
    assert tree_digest(root) == published

    # The exclusion is prefix-anchored, not a blanket dot-file or runtime-name skip.
    (site / "hermes-ssh-runtime-1a2b3c4d5e6f7a8b").write_text("pid=1235\n")
    assert tree_digest(root) != published

    # And a genuine payload change is still caught alongside a live marker.
    (site / "payload.py").write_bytes(b"published = False\n")
    assert tree_digest(root) != published


def test_digest_matches_survives_a_backend_identity_marker(tmp_path):
    """The recorded digest stays valid once a backend has booted against the entry."""
    root = tmp_path / "entry"
    entry = root / "bin"
    entry.mkdir(parents=True)
    (entry / "interpreter").write_bytes(b"\x7fELF payload")
    recorded = tree_digest(root)

    (root / ".hermes-ssh-runtime-9f8e7d6c5b4a3928").write_text("pid=4321\n")
    assert digest_matches(root, recorded)

