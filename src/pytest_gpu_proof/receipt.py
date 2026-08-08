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
    get_gh_cli_login,
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
    # Signer resolution: explicit override > [tool.gpu_proof]/flag config >
    # authenticated gh CLI login (the actual keyholder) > origin-remote owner.
    # The last is only a guess — for org-owned repos it yields the ORG, which
    # has no SSH keys, so verification would fail; warn when we land there.
    github_username = override_github_username or config.github_username
    if not github_username:
        github_username = get_gh_cli_login()
    if not github_username:
        github_username = get_github_username()
        if github_username:
            print(
                f"[gpu-proof] WARNING: signer '{github_username}' was derived "
                "from the origin remote owner, which may be an org with no SSH "
                "keys. If verification fails, set --gpu-proof-github-user or "
                "github_username in [tool.gpu_proof] to the keyholder."
            )
    fingerprint = compute_fingerprint(config.fingerprint_paths)

    # Sharded emission (schema "2", additive): when the run declares a shard
    # name, the receipt carries a `shards` list whose single entry pins THIS
    # shard's own narrow fingerprint (its declared paths, defaulting to the
    # global fingerprint paths) and its test membership by node id. The flat
    # `tests` list remains authoritative for outcomes; the global fingerprint
    # keeps its schema-1 meaning. This is what makes per-shard carry-forward
    # verifiable later: a shard whose narrow fingerprint still recomputes clean
    # provably ran on identical inputs.
    shard_name = getattr(config, "shard_name", None)
    schema_version = "2" if shard_name else "1"
    shards = None
    if shard_name:
        shard_paths = getattr(config, "shard_fingerprint_paths", None) or config.fingerprint_paths
        shards = [{
            "name": shard_name,
            "fingerprint": compute_fingerprint(shard_paths),
            "node_ids": [t["node_id"] for t in test_results],
            "carried": None,
        }]

    payload = {
        "schema_version": schema_version,
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
    if shards is not None:
        payload["shards"] = shards
    return payload


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
