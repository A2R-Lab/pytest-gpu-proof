"""
Build, sign, and write the JSON receipt artifact.

Signing covers the canonical (compact, sorted-key) JSON of the receipt without
the signature field. The signature is then embedded as receipt["signature"].
"""

import base64
import datetime
import json
import platform
import subprocess
import sys
from typing import Any, Dict, List, Optional

from .gitutils import (
    get_branch,
    get_commit_sha,
    get_github_username,
    get_remote_url,
    is_dirty,
)


def _utcnow() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gpu_info() -> Optional[Dict[str, Any]]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            return {
                "name": parts[0] if len(parts) > 0 else None,
                "driver_version": parts[1] if len(parts) > 1 else None,
                "memory": parts[2] if len(parts) > 2 else None,
            }
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _env_info() -> Dict[str, Any]:
    try:
        import pytest
        pytest_version = pytest.__version__
    except ImportError:
        pytest_version = None

    from pytest_gpu_proof import __version__

    return {
        "python_version": sys.version.split()[0],
        "platform": platform.system().lower(),
        "pytest_version": pytest_version,
        "plugin_version": __version__,
        "gpu_info": _gpu_info(),
    }


def canonicalize(receipt_dict: dict) -> bytes:
    return json.dumps(receipt_dict, sort_keys=True, separators=(",", ":")).encode()


def build_receipt_payload(
    config,
    test_results: List[dict],
    started_at: str,
    ended_at: str,
    override_github_username: Optional[str] = None,
) -> dict:
    from .fingerprint import compute_fingerprint

    remote_url = get_remote_url()
    github_username = (
        override_github_username
        or config.github_username
        or get_github_username()
    )
    fingerprint = compute_fingerprint(config.fingerprint_paths)

    return {
        "schema_version": "1",
        "mode": config.mode,
        "repo": {
            "remote_url": remote_url,
            "github_username": github_username,
            "commit_sha": get_commit_sha(),
            "branch": get_branch(),
            "dirty": is_dirty(),
        },
        "fingerprint": fingerprint,
        "session": {
            "started_at": started_at,
            "ended_at": ended_at,
            "node_ids": [t["node_id"] for t in test_results],
        },
        "tests": test_results,
        "environment": _env_info(),
    }


def finalize_receipt(payload: dict, signer) -> dict:
    data = canonicalize(payload)
    sig_bytes = signer.sign(data)

    receipt = dict(payload)
    receipt["signature"] = {
        "algorithm": signer.algorithm(),
        "backend": "ssh-local",
        "signer": payload["repo"].get("github_username") or "unknown",
        "key_fingerprint": signer.key_fingerprint(),
        "value": base64.b64encode(sig_bytes).decode(),
    }
    return receipt


def write_receipt(receipt: dict, path: str) -> None:
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2, sort_keys=True)
        f.write("\n")
