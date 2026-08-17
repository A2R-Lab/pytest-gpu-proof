"""
Merge shard receipts from one commit into a single re-signed receipt.

Motivation: large suites run their GPU tests as several pytest invocations
(per-module crash isolation, machine sharding). Each invocation emits its own
receipt; CI wants ONE artifact to verify. ``gpu-proof merge`` unions the shard
receipts' ``tests`` and re-signs the result with the merger's local SSH key.

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
    schema = receipts[0].get("schema_version")
    if schema not in ("1", "2", "3"):
        raise MergeError(
            f"unsupported schema_version {schema!r} (this version merges "
            f"schema '1', '2', and '3' receipts, not mixed)"
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

    # Sharded receipts: union the shards lists (names must be unique across
    # inputs; a shard's node_ids stay attached to it, so the merged receipt
    # still partitions tests[] by shard for the verifier's membership check).
    merged_shards = None
    if schema == "2" or (schema == "3" and any(r.get("shards") for r in receipts)):
        merged_shards = []
        shard_names: dict = {}
        for src, r in zip(sources, receipts):
            for shard in r.get("shards") or []:
                nm = shard.get("name")
                if nm in shard_names:
                    raise MergeError(
                        f"duplicate shard name {nm!r} in {src} (already from "
                        f"{shard_names[nm]}) — shard names must be unique."
                    )
                shard_names[nm] = src
                merged_shards.append(shard)

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
                "signer": (
                    (r.get("signer") or {}).get("github_user")
                    or (r.get("signature") or {}).get("signer")
                ),
            }
            for src, r, s in zip(sources, receipts, sessions)
        ],
    }
    if schema == "3":
        merged["session"]["outcome"] = (
            "passed"
            if all(s.get("outcome") == "passed" for s in sessions)
            else "failed"
        )
        merged["session"]["pytest_args"] = [
            s.get("pytest_args", []) for s in sessions
        ]
    if merged_shards is not None:
        merged["shards"] = merged_shards
    return merged


def _git_is_ancestor(repo_root: str, ancestor: str, descendant: str) -> bool:
    import subprocess
    try:
        subprocess.run(
            ["git", "-C", repo_root, "merge-base", "--is-ancestor", ancestor, descendant],
            capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def carry_forward(payload: dict, old_receipt: dict, old_source: str,
                  repo_root: str = ".") -> dict:
    """Graft shards from ``old_receipt`` that are ABSENT from the fresh merged
    ``payload``, marking each ``carried``. Soundness conditions per shard:

      1. the old receipt is schema '2' and its commit is an ANCESTOR of the
         fresh payload's commit (same history, older point);
      2. the shard's narrow fingerprint recomputes IDENTICAL against the
         current tree — the inputs that shard proved are unchanged at HEAD.

    Shard signatures are provenance (merge is offline); the re-signed merged
    receipt is the attestation, and the verifier re-checks every carried
    shard's fingerprint and gates them on policy ``allow_carried``."""
    from .fingerprint import FingerprintError, recompute_fingerprint

    if old_receipt.get("schema_version") not in ("2", "3"):
        raise MergeError(
            f"--carry-from {old_source}: not a schema '2'/'3' sharded receipt")
    old_sha = old_receipt.get("repo", {}).get("commit_sha")
    new_sha = payload.get("repo", {}).get("commit_sha")
    if not old_sha or not new_sha:
        raise MergeError("carry-forward receipts must contain commit SHAs")
    if old_sha != new_sha and not _git_is_ancestor(repo_root, old_sha, new_sha):
        raise MergeError(
            f"--carry-from {old_source}: its commit {old_sha[:12]} is not an "
            f"ancestor of {new_sha[:12]} — different history, cannot carry.")

    fresh_names = {s.get("name") for s in payload.get("shards") or []}
    fresh_ids = {t.get("node_id") for t in payload.get("tests", [])}
    old_tests = {t.get("node_id"): t for t in old_receipt.get("tests", [])}
    carried_count = 0
    for shard in old_receipt.get("shards") or []:
        nm = shard.get("name")
        if nm in fresh_names:
            continue  # freshly re-run — the new result wins
        sfp = shard.get("fingerprint", {})
        try:
            snow = recompute_fingerprint(sfp, root=repo_root)
        except FingerprintError as exc:
            raise MergeError(
                f"--carry-from {old_source}: shard {nm!r} fingerprint is invalid: {exc}"
            ) from exc
        if snow["digest"] != sfp.get("digest"):
            raise MergeError(
                f"--carry-from {old_source}: shard {nm!r} fingerprint no longer "
                f"matches the current tree — its inputs changed; re-run it "
                f"instead of carrying.")
        ids = shard.get("node_ids", [])
        dup = fresh_ids.intersection(ids)
        if dup:
            raise MergeError(
                f"--carry-from {old_source}: shard {nm!r} would re-introduce "
                f"node id(s) already present (e.g. {sorted(dup)[0]!r}).")
        grafted = dict(shard)
        grafted["carried"] = {
            "from": old_source.rsplit("/", 1)[-1],
            "original_commit_sha": old_sha,
            "original_ended_at": old_receipt.get("session", {}).get("ended_at"),
            "original_signer": (
                (old_receipt.get("signer") or {}).get("github_user")
                or (old_receipt.get("signature") or {}).get("signer")
            ),
        }
        payload.setdefault("shards", []).append(grafted)
        for nid in ids:
            if nid not in old_tests:
                raise MergeError(
                    f"--carry-from {old_source}: shard {nm!r} claims {nid!r} "
                    f"which is not in its receipt's tests[].")
            payload["tests"].append(old_tests[nid])
            fresh_ids.add(nid)
        carried_count += 1
    payload["session"]["node_ids"] = [t["node_id"] for t in payload["tests"]]
    payload["schema_version"] = str(payload.get("schema_version"))
    if not carried_count:
        print(f"[gpu-proof] merge: nothing to carry from {old_source} "
              f"(all its shards were freshly re-run)")
    return payload


def merge_receipts(
    paths: List[str],
    out: str,
    *,
    github_user: Optional[str] = None,
    key_path: Optional[str] = None,
    unsigned: bool = False,
    carry_from: Optional[str] = None,
    repo_root: str = ".",
) -> dict:
    """Merge receipts at ``paths`` and write the re-signed result to ``out``.

    ``github_user`` overrides the recorded signer identity (default: the first
    shard's ``repo.github_username`` — correct when the merger is also the shard
    runner). ``unsigned=True`` writes ``signature: null`` (verifies only with
    ``--allow-unsigned``, loudly, same as the plugin's 'none' backend).
    ``carry_from`` grafts still-valid shards from an older sharded receipt —
    see :py:func:`carry_forward` for the soundness conditions.
    """
    receipts = [load_receipt(p) for p in paths]
    payload = merge_payloads(receipts, list(paths))
    if carry_from:
        payload = carry_forward(payload, load_receipt(carry_from), carry_from,
                                repo_root=repo_root)
    if github_user:
        payload["repo"] = dict(payload.get("repo", {}))
        payload["repo"]["github_username"] = github_user

    if unsigned:
        receipt = dict(payload)
        receipt["signature"] = None
    else:
        from .signers.ed25519 import SSHSigner
        signer = SSHSigner(key_path=key_path, root=repo_root)
        receipt = finalize_receipt(payload, signer)
    write_receipt(receipt, out)
    return receipt
