"""Deterministic source manifests for receipt binding."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Sequence

from .gitutils import GitError, TrackedEntry, get_tracked_entries, get_tracked_files


FINGERPRINT_ALGORITHM = "sha256-manifest-v2"


class FingerprintError(RuntimeError):
    """Raised when the configured source scope cannot be fingerprinted safely."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _regular_entry(entry: TrackedEntry, root: Path) -> dict:
    path = root / entry.path
    try:
        if entry.mode == "120000":
            return {"kind": "symlink", "mode": entry.mode, "sha256": _sha256_bytes(os.readlink(path).encode())}
        if entry.mode == "160000":
            from .gitutils import get_commit_sha

            # Only trust rev-parse when the submodule is actually initialized
            # there; on an empty checkout dir git would walk up and report the
            # PARENT repo's HEAD.
            initialized = path.is_dir() and (path / ".git").exists()
            head = get_commit_sha(str(path)) if initialized else None
            return {"kind": "gitlink", "mode": entry.mode, "commit": head or entry.object_id}
        return {"kind": "file", "mode": entry.mode, "sha256": _sha256_bytes(path.read_bytes())}
    except OSError as exc:
        raise FingerprintError(f"cannot read fingerprint input {entry.path!r}: {exc}") from exc


def _extra_files(extra_paths: Sequence[str], root: Path) -> list[Path]:
    files: list[Path] = []
    for raw in extra_paths:
        candidate = Path(os.path.abspath(root / raw))
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise FingerprintError(f"fingerprint input escapes repository root: {raw!r}") from exc
        if candidate.is_symlink() or candidate.is_file():
            files.append(candidate)
        elif candidate.is_dir():
            files.extend(path for path in candidate.rglob("*") if path.is_file() or path.is_symlink())
        else:
            raise FingerprintError(f"explicit fingerprint input does not exist: {raw!r}")
    return sorted(set(files), key=lambda path: path.as_posix())


def compute_fingerprint(
    paths: Sequence[str],
    root: str = ".",
    *,
    extra_paths: Sequence[str] = (),
    exclude_paths: Sequence[str] = (),
) -> dict:
    """Hash tracked inputs plus explicitly requested generated/ignored inputs.

    Directories in ``paths`` select Git-tracked entries only. Generated or
    ignored artifacts must be named through ``extra_paths`` so build debris is
    never swept into a receipt accidentally.
    """
    root_path = Path(root).resolve()
    clean_paths = sorted(dict.fromkeys(str(path) for path in paths if str(path)))
    clean_extra = sorted(dict.fromkeys(str(path) for path in extra_paths if str(path)))
    clean_excluded = sorted(
        dict.fromkeys(str(path) for path in exclude_paths if str(path))
    )
    if not clean_paths and not clean_extra:
        raise FingerprintError("fingerprint scope is empty")

    try:
        tracked = get_tracked_entries(clean_paths, str(root_path)) if clean_paths else []
    except GitError as exc:
        raise FingerprintError(str(exc)) from exc

    manifest = {
        entry.path: _regular_entry(entry, root_path)
        for entry in tracked
        if entry.path not in clean_excluded
    }
    for path in _extra_files(clean_extra, root_path):
        rel = path.relative_to(root_path).as_posix()
        if rel in manifest or rel in clean_excluded:
            continue
        try:
            if path.is_symlink():
                manifest[rel] = {"kind": "extra-symlink", "sha256": _sha256_bytes(os.readlink(path).encode())}
            else:
                manifest[rel] = {"kind": "extra-file", "sha256": _sha256_bytes(path.read_bytes())}
        except OSError as exc:
            raise FingerprintError(f"cannot read fingerprint input {rel!r}: {exc}") from exc

    if not manifest:
        raise FingerprintError(
            "fingerprint scope matched zero files; fix fingerprint_paths or "
            "fingerprint_extra_paths"
        )
    canonical = json.dumps({"files": manifest}, sort_keys=True, separators=(",", ":"))
    return {
        "algorithm": FINGERPRINT_ALGORITHM,
        "included_paths": clean_paths,
        "extra_paths": clean_extra,
        "excluded_paths": clean_excluded,
        "file_count": len(manifest),
        "digest": _sha256_bytes(canonical.encode()),
    }


def compute_legacy_fingerprint(paths: Sequence[str], root: str = ".") -> dict:
    """Reproduce the schema-1/2 fingerprint algorithm for old receipts."""
    file_hashes = {}
    try:
        tracked = get_tracked_files(paths, root)
    except GitError as exc:
        raise FingerprintError(str(exc)) from exc
    for rel in tracked:
        path = Path(root) / rel
        if not path.is_file():
            continue
        try:
            file_hashes[rel] = _sha256_bytes(path.read_bytes())
        except OSError as exc:
            raise FingerprintError(f"cannot read legacy fingerprint input {rel!r}: {exc}") from exc
    canonical = json.dumps(
        {"files": {key: file_hashes[key] for key in sorted(file_hashes)}},
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "algorithm": "sha256",
        "included_paths": sorted(paths),
        "file_count": len(file_hashes),
        "digest": _sha256_bytes(canonical.encode()),
    }


def recompute_fingerprint(stored: dict, root: str = ".") -> dict:
    algorithm = stored.get("algorithm")
    paths = stored.get("included_paths")
    if not isinstance(paths, list):
        raise FingerprintError("fingerprint included_paths must be a list")
    if algorithm == FINGERPRINT_ALGORITHM:
        extras = stored.get("extra_paths", [])
        if not isinstance(extras, list):
            raise FingerprintError("fingerprint extra_paths must be a list")
        excluded = stored.get("excluded_paths", [])
        if not isinstance(excluded, list):
            raise FingerprintError("fingerprint excluded_paths must be a list")
        return compute_fingerprint(
            paths, root, extra_paths=extras, exclude_paths=excluded
        )
    if algorithm == "sha256":
        return compute_legacy_fingerprint(paths, root)
    raise FingerprintError(f"unsupported fingerprint algorithm: {algorithm!r}")
