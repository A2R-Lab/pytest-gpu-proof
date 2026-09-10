"""Build, sign, and atomically write receipt artifacts."""

from __future__ import annotations

import base64
import datetime
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .gitutils import (
    get_branch,
    get_commit_sha,
    get_gh_cli_login,
    get_github_username,
    get_remote_url,
    is_dirty,
    require_repository,
)


def _utcnow() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gpu_info() -> Optional[Dict[str, Any]]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid,name,driver_version,memory.total,compute_cap",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    devices = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        devices.append(
            {
                "index": parts[0] if len(parts) > 0 else None,
                "uuid": parts[1] if len(parts) > 1 else None,
                "name": parts[2] if len(parts) > 2 else None,
                "driver_version": parts[3] if len(parts) > 3 else None,
                "memory": parts[4] if len(parts) > 4 else None,
                "compute_capability": parts[5] if len(parts) > 5 else None,
            }
        )
    return {
        "devices": devices,
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }


def _env_info() -> Dict[str, Any]:
    import pytest

    from pytest_gpu_proof import __version__

    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "pytest_version": pytest.__version__,
        "plugin_version": __version__,
        "gpu_info": _gpu_info(),
    }


def canonicalize(receipt_dict: dict) -> bytes:
    try:
        return json.dumps(
            receipt_dict,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"receipt contains a non-JSON value: {exc}") from exc


def _resolve_github_username(config, override: Optional[str], root: str) -> str:
    username = override or config.github_username or get_gh_cli_login()
    if username:
        return username
    username = get_github_username(root)
    if username:
        print(
            f"[gpu-proof] WARNING: signer {username!r} was derived from the "
            "origin owner; set --gpu-proof-github-user for organization repos."
        )
        return username
    raise ValueError(
        "cannot determine signer GitHub username; pass --gpu-proof-github-user"
    )


def build_receipt_payload(
    config,
    test_results: List[dict],
    started_at: str,
    ended_at: str,
    override_github_username: Optional[str] = None,
    *,
    session_outcome: str = "passed",
    collected_node_ids: Optional[List[str]] = None,
) -> dict:
    from .fingerprint import compute_fingerprint

    root = str(Path(config.repo_root).resolve())
    require_repository(root)
    username = _resolve_github_username(config, override_github_username, root)
    excluded_paths = config.fingerprint_excluded_paths
    output = Path(config.output)
    if not output.is_absolute():
        output = Path(root) / output
    try:
        output_rel = output.resolve(strict=False).relative_to(Path(root)).as_posix()
    except ValueError:
        output_rel = None
    dirty_exclusions = [output_rel] if output_rel in excluded_paths else []
    fingerprint = compute_fingerprint(
        config.fingerprint_paths,
        root,
        extra_paths=config.fingerprint_extra_paths,
        exclude_paths=excluded_paths,
    )
    node_ids = collected_node_ids or [test["node_id"] for test in test_results]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("collected GPU-proof node IDs are not unique")

    payload = {
        "schema_version": "3",
        "mode": config.mode,
        "repo": {
            "remote_url": get_remote_url(root),
            "github_username": username,
            "commit_sha": get_commit_sha(root, required=True),
            "branch": get_branch(root),
            "dirty": is_dirty(
                root, required=True, exclude_paths=dirty_exclusions
            ),
        },
        "fingerprint": fingerprint,
        "session": {
            "started_at": started_at,
            "ended_at": ended_at,
            "outcome": session_outcome,
            "node_ids": list(node_ids),
            "pytest_args": list(config.invocation_args),
        },
        "tests": test_results,
        "environment": _env_info(),
    }

    if config.shard_name:
        shard_paths = config.shard_fingerprint_paths or config.fingerprint_paths
        shard_extras = (
            config.fingerprint_extra_paths
            if config.shard_fingerprint_extra_paths is None
            else config.shard_fingerprint_extra_paths
        )
        payload["shards"] = [
            {
                "name": config.shard_name,
                "fingerprint": compute_fingerprint(
                    shard_paths,
                    root,
                    extra_paths=shard_extras,
                    exclude_paths=excluded_paths,
                ),
                "node_ids": list(node_ids),
                "environment": payload["environment"],
                "started_at": started_at,
                "ended_at": ended_at,
                "carried": None,
            }
        ]
    return payload


def finalize_receipt(payload: dict, signer) -> dict:
    """Bind signer metadata inside the signed schema-3 payload."""
    signed_payload = dict(payload)
    schema = str(payload.get("schema_version", "1"))
    if schema == "3":
        signed_payload["signer"] = {
            "github_user": payload.get("repo", {}).get("github_username"),
            "algorithm": signer.algorithm(),
            "backend": "ssh-local",
            "key_fingerprint": signer.key_fingerprint(),
        }
        signature = signer.sign(canonicalize(signed_payload))
        receipt = dict(signed_payload)
        receipt["signature"] = {"value": base64.b64encode(signature).decode()}
        return receipt

    signature = signer.sign(canonicalize(payload))
    receipt = dict(payload)
    receipt["signature"] = {
        "algorithm": signer.algorithm(),
        "backend": "ssh-local",
        "signer": payload.get("repo", {}).get("github_username") or "unknown",
        "key_fingerprint": signer.key_fingerprint(),
        "value": base64.b64encode(signature).decode(),
    }
    return receipt


def write_receipt(receipt: dict, path: str) -> None:
    """Validate JSON serialization and replace the destination atomically."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=destination.parent, prefix=f".{destination.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
