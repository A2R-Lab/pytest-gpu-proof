import hashlib
import json
import os
from typing import List

from .gitutils import get_tracked_files


def _hash_file(path: str, root: str) -> str:
    h = hashlib.sha256()
    with open(os.path.join(root, path), "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_fingerprint(paths: List[str], root: str = ".") -> dict:
    tracked = get_tracked_files(paths, root)
    file_hashes = {}
    for p in tracked:
        try:
            file_hashes[p] = _hash_file(p, root)
        except OSError:
            pass

    canonical = json.dumps(
        {"files": {k: file_hashes[k] for k in sorted(file_hashes)}},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()

    return {
        "algorithm": "sha256",
        "included_paths": sorted(paths),
        "file_count": len(file_hashes),
        "digest": digest,
    }
