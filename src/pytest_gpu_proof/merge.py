"""
Merge shard receipts from one commit into a single re-signed receipt.

Motivation: large suites run their GPU tests as several pytest invocations
(per-module crash isolation, machine sharding). Each invocation emits its own
receipt; CI wants ONE artifact to verify. ``gpu-proof merge`` unions the shard
receipts' ``tests`` and re-signs the result with the merger's local SSH key —
so the merged receipt flows through the existing ``gpu-proof verify`` path
completely unchanged (schema_version stays "1"; the only addition is the
OPTIONAL ``session.shards`` provenance list, which the verifier ignores).

Trust model (consistent with docs/security_model.md): the merged receipt is an
attestation by the MERGER — shard signatures are recorded as provenance but are
NOT verified here (merge is offline by design); the merged receipt's signature
is what CI verifies. Merging refuses to combine shards that disagree on
anything a receipt pins: schema, commit SHA, fingerprint, mode, or the
environment the tests ran under. Duplicate node IDs are always an error — two
shards attesting the same test is a sharding bug, not a merge input.
"""

import json
import os
from typing import List, Optional

from .receipt import finalize_receipt, write_receipt


class MergeError(ValueError):
    """A refusal to merge, with an actionable message."""


def load_receipt(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise MergeError(f"{path}: not a readable receipt ({e})") from e
    if not isinstance(data, dict) or "tests" not in data:
        raise MergeError(f"{path}: not a gpu-proof receipt (no 'tests' key)")
    return data


def _require_identical(receipts: List[dict], sources: List[str], getter, what: str):
    values = [getter(r) for r in receipts]
    first = values[0]
    for src, val in zip(sources[1:], values[1:]):
        if val != first:
            raise MergeError(
                f"shards disagree on {what}: {sources[0]}={first!r} vs {src}={val!r} — "
                f"a merged receipt must come from ONE commit/config; re-run the "
                f"divergent shard."
            )
    return first


def merge_payloads(receipts: List[dict], sources: List[str]) -> dict:
    """Union shard payloads into one UNSIGNED payload. Raises MergeError on any
    disagreement over what a receipt pins."""
    if len(receipts) < 1:
        raise MergeError("nothing to merge")

    _require_identical(receipts, sources, lambda r: r.get("schema_version"), "schema_version")
    if receipts[0].get("schema_version") != "1":
        raise MergeError(
            f"unsupported schema_version {receipts[0].get('schema_version')!r} "
            f"(this version merges schema '1' receipts)"
        )
    _require_identical(receipts, sources, lambda r: r.get("repo", {}).get("commit_sha"),
                       "repo.commit_sha")
    _require_identical(receipts, sources, lambda r: r.get("fingerprint"), "fingerprint")
    _require_identical(receipts, sources, lambda r: r.get("mode"), "mode")
    for key in ("python_version", "platform", "pytest_version", "plugin_version"):
        _require_identical(receipts, sources,
                           lambda r, k=key: r.get("environment", {}).get(k),
                           f"environment.{key}")

    # tests: union; duplicate node ids are a sharding bug, never silently deduped.
    tests: List[dict] = []
    seen: dict = {}
    for src, r in zip(sources, receipts):
        for t in r.get("tests", []):
            nid = t.get("node_id")
            if nid in seen:
                raise MergeError(
                    f"duplicate node_id {nid!r} in {src} (already attested by "
                    f"{seen[nid]}) — shards must partition the suite."
                )
            seen[nid] = src
            tests.append(t)
    if not tests:
        raise MergeError("merged receipt would contain zero tests")

    sessions = [r.get("session", {}) for r in receipts]
    started = min(s.get("started_at") for s in sessions)
    ended = max(s.get("ended_at") for s in sessions)

    merged = dict(receipts[0])
    merged.pop("signature", None)
    # repo: the commit SHA is asserted identical above; branch/remote come from
    # the first shard. `dirty` is OR-ed — one dirty shard makes the merged
    # attestation dirty, and the verifier's dirty policy then applies honestly.
    merged["repo"] = dict(receipts[0].get("repo", {}))
    merged["repo"]["dirty"] = any(r.get("repo", {}).get("dirty") for r in receipts)
    # environment: fields asserted identical above; gpu_info from the first
    # shard that has one (a CPU-only shard shouldn't erase the GPU record).
    merged["environment"] = dict(receipts[0].get("environment", {}))
    merged["environment"]["gpu_info"] = next(
        (r["environment"]["gpu_info"] for r in receipts
         if r.get("environment", {}).get("gpu_info")), None)
    merged["tests"] = tests
    merged["session"] = {
        "started_at": started,
        "ended_at": ended,
        "node_ids": [t["node_id"] for t in tests],
        # Provenance (additive; the verifier ignores unknown session keys).
        # Shard signers are recorded, not verified — the merged signature is
        # the attestation CI checks.
        "shards": [
            {
                "source": os.path.basename(src),
                "node_count": len(r.get("tests", [])),
                "started_at": s.get("started_at"),
                "ended_at": s.get("ended_at"),
                "signer": (r.get("signature") or {}).get("signer"),
            }
            for src, r, s in zip(sources, receipts, sessions)
        ],
    }
    return merged


def merge_receipts(
    paths: List[str],
    out: str,
    *,
    github_user: Optional[str] = None,
    key_path: Optional[str] = None,
    unsigned: bool = False,
) -> dict:
    """Merge receipts at ``paths`` and write the re-signed result to ``out``.

    ``github_user`` overrides the recorded signer identity (default: the first
    shard's ``repo.github_username`` — correct when the merger is also the shard
    runner). ``unsigned=True`` writes ``signature: null`` (verifies only with
    ``--allow-unsigned``, loudly, same as the plugin's 'none' backend).
    """
    receipts = [load_receipt(p) for p in paths]
    payload = merge_payloads(receipts, list(paths))
    if github_user:
        payload["repo"] = dict(payload.get("repo", {}))
        payload["repo"]["github_username"] = github_user

    if unsigned:
        receipt = dict(payload)
        receipt["signature"] = None
    else:
        from .signers.ed25519 import SSHSigner
        signer = SSHSigner(key_path=key_path)
        receipt = finalize_receipt(payload, signer)
    write_receipt(receipt, out)
    return receipt
