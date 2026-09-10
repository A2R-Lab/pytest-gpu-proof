"""Small, strict git helpers used by receipt capture and verification."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence


class GitError(RuntimeError):
    """Raised when a trust-relevant git query cannot be completed."""


@dataclass(frozen=True)
class TrackedEntry:
    path: str
    mode: str
    object_id: str


def _git(*args: str, root: str = ".", required: bool = False) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        if required:
            detail = getattr(exc, "stderr", "") or str(exc)
            raise GitError(f"git {' '.join(args)} failed in {root}: {detail.strip()}") from exc
        return None
    return result.stdout.strip() or None


def require_repository(root: str = ".") -> None:
    if _git("rev-parse", "--show-toplevel", root=root) is None:
        raise GitError(f"{root!r} is not inside a git repository")


def get_commit_sha(root: str = ".", *, required: bool = False) -> Optional[str]:
    return _git("rev-parse", "HEAD", root=root, required=required)


def get_branch(root: str = ".") -> Optional[str]:
    return _git("rev-parse", "--abbrev-ref", "HEAD", root=root)


def is_dirty(
    root: str = ".",
    *,
    required: bool = False,
    exclude_paths: Sequence[str] = (),
) -> bool:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                root,
                "status",
                "--porcelain",
                "-z",
                "--ignore-submodules=untracked",
            ],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        if required:
            raise GitError(f"could not inspect git status in {root}") from exc
        return False
    excluded = set(exclude_paths)
    records = result.stdout.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:2]
        paths = [record[3:].decode("utf-8", errors="surrogateescape")]
        if b"R" in status or b"C" in status:
            if index < len(records) and records[index]:
                paths.append(
                    records[index].decode("utf-8", errors="surrogateescape")
                )
                index += 1
        if any(path not in excluded for path in paths):
            return True
    return False


def get_remote_url(root: str = ".") -> Optional[str]:
    return _git("remote", "get-url", "origin", root=root)


def extract_github_username(remote_url: str) -> Optional[str]:
    match = re.search(r"github\.com[:/]([^/]+)/", remote_url)
    return match.group(1) if match else None


def get_github_username(root: str = ".") -> Optional[str]:
    url = get_remote_url(root)
    return extract_github_username(url) if url else None


def get_gh_cli_login() -> Optional[str]:
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return None
    return result.stdout.strip() or None


def get_git_signing_key(root: str = ".") -> Optional[str]:
    value = _git("config", "--get", "user.signingKey", root=root)
    return os.path.expanduser(value) if value else None


def get_tracked_entries(paths: Sequence[str], root: str = ".") -> list[TrackedEntry]:
    """Return stage-0 tracked entries under *paths*, including gitlinks."""
    if not paths:
        raise GitError("fingerprint path list is empty")
    try:
        result = subprocess.run(
            ["git", "-C", root, "ls-files", "--stage", "-z", "--", *paths],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise GitError(f"could not enumerate tracked files in {root}") from exc

    entries: list[TrackedEntry] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, object_id, stage = metadata.decode().split()
        if stage != "0":
            raise GitError(f"unmerged index entry cannot be fingerprinted: {raw_path!r}")
        entries.append(
            TrackedEntry(
                path=raw_path.decode("utf-8", errors="surrogateescape"),
                mode=mode,
                object_id=object_id,
            )
        )
    return sorted(entries, key=lambda entry: entry.path)


def get_tracked_files(paths: Sequence[str], root: str = ".") -> list[str]:
    """Compatibility wrapper retained for legacy fingerprint verification."""
    return [entry.path for entry in get_tracked_entries(paths, root)]
