"""
Standalone receipt verifier.

Checks:
  1. Signature — fetches signer's public keys from github.com/{username}.keys
  2. Fingerprint — recomputes and compares digest
  3. Commit SHA — compares against current repo state
  4. Test outcomes — all tests in receipt must have passed
  5. Freshness — receipt must not be older than max_age_days
  6. Dirty policy — reject dirty-tree receipts if policy requires clean
"""

import base64
import datetime
import json
import sys
from pathlib import Path
from typing import Optional

from .signers.ed25519 import verify_with_github_keys
from .signers.base import VerifierError as _VerifierError


class VerificationError(Exception):
    pass


def _load_policy(policy_path: Optional[str]) -> dict:
    if not policy_path:
        return {}
    try:
        import yaml  # type: ignore
        with open(policy_path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        import json as _json
        with open(policy_path) as f:
            return _json.load(f)


def _receipt_payload_without_sig(receipt: dict) -> bytes:
    from .receipt import canonicalize
    payload = {k: v for k, v in receipt.items() if k != "signature"}
    return canonicalize(payload)


def verify_receipt(
    receipt_path: str,
    policy_path: Optional[str] = None,
    repo_root: str = ".",
    github_user_override: Optional[str] = None,
    max_age_days: Optional[int] = None,
) -> bool:
    try:
        _verify(receipt_path, policy_path, repo_root, github_user_override, max_age_days)
        return True
    except VerificationError as e:
        print(f"[gpu-proof] FAIL: {e}", file=sys.stderr)
        return False


def _verify(
    receipt_path: str,
    policy_path: Optional[str],
    repo_root: str,
    github_user_override: Optional[str],
    max_age_days_override: Optional[int],
):
    # --- load receipt ---
    receipt_text = Path(receipt_path).read_text()
    receipt = json.loads(receipt_text)

    schema = receipt.get("schema_version")
    if schema != "1":
        raise VerificationError(f"Unknown schema_version: {schema!r}")

    sig_block = receipt.get("signature")
    if not sig_block:
        raise VerificationError("Receipt has no signature block")

    sig_b64 = sig_block.get("value", "")
    if not sig_b64:
        raise VerificationError("Signature value is missing")

    try:
        signature = base64.b64decode(sig_b64)
    except Exception:
        raise VerificationError("Signature value is not valid base64")

    # --- verify signature via GitHub public keys ---
    github_username = (
        github_user_override
        or sig_block.get("signer")
        or receipt.get("repo", {}).get("github_username")
    )
    if not github_username:
        raise VerificationError(
            "Cannot determine GitHub username. Pass --github-user=USERNAME."
        )

    payload_bytes = _receipt_payload_without_sig(receipt)

    print(f"[gpu-proof] Fetching public keys for @{github_username} …")
    try:
        ok = verify_with_github_keys(payload_bytes, signature, github_username)
    except _VerifierError as e:
        raise VerificationError(str(e))

    if not ok:
        raise VerificationError(
            f"Signature does not match any SSH key registered by @{github_username} on GitHub"
        )
    print(f"[gpu-proof] Signature valid (signer: @{github_username})")

    # --- recompute fingerprint ---
    repo = receipt.get("repo", {})
    stored_fp = receipt.get("fingerprint", {})
    fp_paths = stored_fp.get("included_paths", ["src", "tests"])

    from .fingerprint import compute_fingerprint  # noqa: PLC0415 (local import ok here)

    current_fp = compute_fingerprint(fp_paths, root=repo_root)
    if current_fp["digest"] != stored_fp.get("digest"):
        raise VerificationError(
            f"Fingerprint mismatch: stored={stored_fp.get('digest')[:12]}… "
            f"current={current_fp['digest'][:12]}…\n"
            "The code under src/ or tests/ has changed since the receipt was generated."
        )
    print(f"[gpu-proof] Fingerprint OK ({current_fp['digest'][:12]}…)")

    # --- commit SHA check ---
    from .gitutils import get_commit_sha

    current_sha = get_commit_sha()
    stored_sha = repo.get("commit_sha")
    if current_sha and stored_sha and current_sha != stored_sha:
        raise VerificationError(
            f"Commit SHA mismatch: receipt={stored_sha[:12]}  current={current_sha[:12]}"
        )
    if stored_sha:
        print(f"[gpu-proof] Commit SHA OK ({stored_sha[:12]}…)")

    # --- dirty repo policy ---
    policy = _load_policy(policy_path)
    allow_dirty = policy.get("allow_dirty", True)
    if repo.get("dirty") and not allow_dirty:
        raise VerificationError(
            "Receipt was generated from a dirty repository and policy requires a clean tree"
        )

    # --- test outcomes ---
    tests = receipt.get("tests", [])
    if not tests:
        raise VerificationError("Receipt contains no test results")

    failed = [t["node_id"] for t in tests if t.get("outcome") != "passed"]
    if failed:
        raise VerificationError(
            f"{len(failed)} test(s) did not pass: {', '.join(failed)}"
        )
    print(f"[gpu-proof] All {len(tests)} test(s) passed")

    # --- freshness ---
    max_days = max_age_days_override or policy.get("max_age_days", 30)
    signed_at_str = receipt.get("session", {}).get("ended_at")
    if signed_at_str:
        try:
            signed_at = datetime.datetime.strptime(signed_at_str, "%Y-%m-%dT%H:%M:%SZ")
            age = (datetime.datetime.utcnow() - signed_at).days
            if age > max_days:
                raise VerificationError(
                    f"Receipt is {age} days old; policy allows max {max_days} days"
                )
            print(f"[gpu-proof] Freshness OK (age: {age} day(s), limit: {max_days})")
        except ValueError:
            pass

    print(f"[gpu-proof] Receipt verified successfully.")
