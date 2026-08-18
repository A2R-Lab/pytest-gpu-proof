"""Strict, CPU-only verification of signed pytest GPU receipts."""

from __future__ import annotations

import base64
import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .fingerprint import FingerprintError, recompute_fingerprint
from .gitutils import GitError, get_commit_sha, is_dirty, require_repository
from .signers.base import VerifierError as _VerifierError
from .signers.ed25519 import (
    _public_key_fingerprint,
    find_verifying_github_key,
    public_key_algorithm,
)


class VerificationError(Exception):
    pass


_POLICY_KEYS = {
    "allow_carried",
    "allow_dirty",
    "allowed_key_fingerprints",
    "allowed_signers",
    "carried_max_age_days",
    "max_age_days",
    "min_schema",
    "require_mode",
    "required_fingerprint_extra_paths",
    "required_fingerprint_excluded_paths",
    "required_fingerprint_paths",
    "required_shard_fingerprints",
    "required_test_manifest",
    "signer_mode",
}


def _load_policy(policy_path: Optional[str]) -> dict:
    if not policy_path:
        return {}
    path = Path(policy_path)
    try:
        text = path.read_text()
        if path.suffix.lower() == ".json":
            policy = json.loads(text)
        else:
            try:
                import yaml  # type: ignore
            except ImportError as exc:
                raise VerificationError(
                    "YAML policy requires the 'yaml' extra: pip install "
                    "pytest-gpu-proof[yaml]"
                ) from exc
            policy = yaml.safe_load(text)
    except VerificationError:
        raise
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise VerificationError(f"cannot read policy {policy_path!r}: {exc}") from exc
    if policy is None:
        return {}
    if not isinstance(policy, dict):
        raise VerificationError("policy must be a JSON/YAML object")
    unknown = sorted(set(policy) - _POLICY_KEYS)
    if unknown:
        raise VerificationError(f"unknown policy field(s): {', '.join(unknown)}")

    def string_list(name: str) -> None:
        value = policy.get(name)
        if value is not None and (
            not isinstance(value, list)
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise VerificationError(f"policy field {name!r} must be a list of strings")

    for name in (
        "allowed_key_fingerprints",
        "allowed_signers",
        "required_fingerprint_excluded_paths",
        "required_fingerprint_extra_paths",
        "required_fingerprint_paths",
    ):
        string_list(name)
    for name in ("allow_carried", "allow_dirty"):
        if name in policy and type(policy[name]) is not bool:
            raise VerificationError(f"policy field {name!r} must be a boolean")
    for name in ("carried_max_age_days", "max_age_days"):
        if name in policy and (
            type(policy[name]) is not int or policy[name] < 0
        ):
            raise VerificationError(
                f"policy field {name!r} must be a non-negative integer"
            )
    if "min_schema" in policy and policy["min_schema"] not in {1, 2, 3}:
        raise VerificationError("policy field 'min_schema' must be 1, 2, or 3")
    if "require_mode" in policy and policy["require_mode"] not in {
        "local",
        "ci-gpu",
    }:
        raise VerificationError("policy field 'require_mode' must be 'local' or 'ci-gpu'")
    if "required_test_manifest" in policy and not isinstance(
        policy["required_test_manifest"], str
    ):
        raise VerificationError("policy field 'required_test_manifest' must be a path string")
    shard_policy = policy.get("required_shard_fingerprints")
    if shard_policy is not None:
        if not isinstance(shard_policy, dict):
            raise VerificationError("required_shard_fingerprints must be an object")
        for name, scope in shard_policy.items():
            if not isinstance(name, str) or not isinstance(scope, dict):
                raise VerificationError("each required shard scope must be an object")
            unknown_scope = set(scope) - {"paths", "extra_paths", "excluded_paths"}
            if unknown_scope:
                raise VerificationError(f"shard {name!r} has unknown policy fields")
            for field in ("paths", "extra_paths", "excluded_paths"):
                value = scope.get(field, [])
                if not isinstance(value, list) or not all(
                    isinstance(item, str) and item for item in value
                ):
                    raise VerificationError(
                        f"shard {name!r} field {field!r} must be a list of strings"
                    )
    mode = policy.get("signer_mode", "open")
    if mode not in {"open", "restricted"}:
        raise VerificationError("signer_mode must be 'open' or 'restricted'")
    if mode == "restricted" and not (
        policy.get("allowed_signers") or policy.get("allowed_key_fingerprints")
    ):
        raise VerificationError("restricted signer policy has no allowlist")
    return policy


def _load_node_ids(path: Path) -> set[str]:
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise VerificationError(f"cannot read node-id manifest {path}: {exc}") from exc
    return {
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    }


def _receipt_payload_without_sig(receipt: dict) -> bytes:
    from .receipt import canonicalize

    return canonicalize({key: value for key, value in receipt.items() if key != "signature"})


def _is_ancestor(repo_root: str, ancestor_sha: str, descendant_sha: str) -> bool:
    try:
        subprocess.run(
            ["git", "-C", repo_root, "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def _require_dict(container: dict, key: str) -> dict:
    value = container.get(key)
    if not isinstance(value, dict):
        raise VerificationError(f"receipt field {key!r} must be an object")
    return value


def _parse_time(value, field: str) -> datetime.datetime:
    if not isinstance(value, str):
        raise VerificationError(f"{field} is missing or is not a UTC timestamp")
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.UTC
        )
    except ValueError as exc:
        raise VerificationError(f"{field} is not a valid UTC timestamp: {value!r}") from exc


def _validate_structure(receipt: dict, schema: str) -> tuple[dict, dict, list]:
    repo = _require_dict(receipt, "repo")
    session = _require_dict(receipt, "session")
    _require_dict(receipt, "fingerprint")
    _require_dict(receipt, "environment")
    if receipt.get("mode") not in {"local", "ci-gpu"}:
        raise VerificationError("receipt mode is missing or invalid")
    if not isinstance(repo.get("commit_sha"), str) or not repo["commit_sha"]:
        raise VerificationError("receipt repo.commit_sha is missing")
    tests = receipt.get("tests")
    if not isinstance(tests, list) or not tests:
        raise VerificationError("receipt contains no test results")
    node_ids = []
    for index, test in enumerate(tests):
        if not isinstance(test, dict) or not isinstance(test.get("node_id"), str):
            raise VerificationError(f"tests[{index}] has no valid node_id")
        node_ids.append(test["node_id"])
        if test.get("outcome") not in {"passed", "failed", "error", "skipped"}:
            raise VerificationError(f"tests[{index}] has an invalid outcome")
        checks = test.get("checks", [])
        if not isinstance(checks, list):
            raise VerificationError(f"tests[{index}].checks must be a list")
        for check_index, check in enumerate(checks):
            if not isinstance(check, dict) or check.get("outcome") not in {
                "passed",
                "failed",
                "error",
            }:
                raise VerificationError(
                    f"tests[{index}].checks[{check_index}] is invalid"
                )
    if len(node_ids) != len(set(node_ids)):
        raise VerificationError("receipt contains duplicate test node IDs")
    recorded = session.get("node_ids")
    if not isinstance(recorded, list) or recorded != node_ids:
        raise VerificationError("session.node_ids does not exactly match tests[]")
    started = _parse_time(session.get("started_at"), "session.started_at")
    ended = _parse_time(session.get("ended_at"), "session.ended_at")
    if ended < started:
        raise VerificationError("session.ended_at precedes session.started_at")
    if schema == "3" and session.get("outcome") not in {"passed", "failed"}:
        raise VerificationError("schema-3 session.outcome is missing or invalid")
    return repo, session, tests


def _verify_signature(receipt: dict, schema: str, override: Optional[str], policy: dict):
    sig = receipt.get("signature")
    if not sig:
        if policy.get("signer_mode", "open") == "restricted":
            raise VerificationError(
                "repository policy restricts signers; unsigned receipts are not acceptable"
            )
        return None, None, None
    if not isinstance(sig, dict) or not isinstance(sig.get("value"), str):
        raise VerificationError("signature.value is missing")
    try:
        signature = base64.b64decode(sig["value"], validate=True)
    except ValueError as exc:
        raise VerificationError("signature.value is not valid base64") from exc

    if schema == "3":
        signer = _require_dict(receipt, "signer")
        username = signer.get("github_user")
        fingerprint = signer.get("key_fingerprint")
        algorithm = signer.get("algorithm")
        if not all(isinstance(value, str) and value for value in (username, fingerprint, algorithm)):
            raise VerificationError("schema-3 signer identity is incomplete")
        if override and override != username:
            raise VerificationError(
                f"--github-user {override!r} does not match the signed identity @{username}"
            )
        try:
            key = find_verifying_github_key(
                _receipt_payload_without_sig(receipt), signature, username
            )
        except _VerifierError as exc:
            raise VerificationError(str(exc)) from exc
        if key is None:
            raise VerificationError(f"signature does not match a current GitHub key for @{username}")
        if _public_key_fingerprint(key) != fingerprint:
            raise VerificationError("signed key_fingerprint does not match the verifying key")
        if public_key_algorithm(key) != algorithm:
            raise VerificationError("signed algorithm does not match the verifying key")
    else:
        username = override or sig.get("signer") or receipt.get("repo", {}).get("github_username")
        if not isinstance(username, str) or not username:
            raise VerificationError("cannot determine legacy receipt signer")
        try:
            key = find_verifying_github_key(
                _receipt_payload_without_sig(receipt), signature, username
            )
        except _VerifierError as exc:
            raise VerificationError(str(exc)) from exc
        if key is None:
            raise VerificationError(f"signature does not match a current GitHub key for @{username}")
        # The policy-checked fingerprint must come from the key that actually
        # verified, never from the unsigned envelope (which anyone can edit).
        fingerprint = _public_key_fingerprint(key)
        asserted = sig.get("key_fingerprint")
        if isinstance(asserted, str) and asserted and asserted != fingerprint:
            raise VerificationError(
                "legacy signature.key_fingerprint does not match the verifying key"
            )

    if policy.get("signer_mode", "open") == "restricted":
        users = set(policy.get("allowed_signers", []))
        fingerprints = set(policy.get("allowed_key_fingerprints", []))
        if users and username not in users:
            raise VerificationError(f"signer @{username} is not allowed by repository policy")
        if fingerprints and fingerprint not in fingerprints:
            raise VerificationError("signing key is not allowed by repository policy")
    return username, fingerprint, schema


def verify_receipt(
    receipt_path: str,
    policy_path: Optional[str] = None,
    repo_root: str = ".",
    github_user_override: Optional[str] = None,
    max_age_days: Optional[int] = None,
    allow_unsigned: bool = False,
    allow_skipped: bool = False,
    require_gpu: Optional[bool] = None,
    expected_skips_path: Optional[str] = None,
) -> bool:
    try:
        _verify(
            receipt_path,
            policy_path,
            repo_root,
            github_user_override,
            max_age_days,
            allow_unsigned=allow_unsigned,
            allow_skipped=allow_skipped,
            require_gpu=require_gpu,
            expected_skips_path=expected_skips_path,
        )
    except VerificationError as exc:
        print(f"[gpu-proof] FAIL: {exc}", file=sys.stderr)
        return False
    return True


def _verify(
    receipt_path: str,
    policy_path: Optional[str],
    repo_root: str,
    github_user_override: Optional[str],
    max_age_days_override: Optional[int],
    allow_unsigned: bool = False,
    allow_skipped: bool = False,
    expected_skips_path: Optional[str] = None,
    require_gpu: Optional[bool] = None,
):
    from .config import load_toml_defaults

    root = str(Path(repo_root).resolve())
    try:
        require_repository(root)
        current_sha = get_commit_sha(root, required=True)
    except GitError as exc:
        raise VerificationError(str(exc)) from exc
    try:
        receipt = json.loads(Path(receipt_path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read receipt {receipt_path!r}: {exc}") from exc
    if not isinstance(receipt, dict):
        raise VerificationError("receipt must be a JSON object")
    schema = str(receipt.get("schema_version"))
    if schema not in {"1", "2", "3"}:
        raise VerificationError(f"unknown schema_version: {schema!r}")
    if schema == "1" and "shards" in receipt:
        raise VerificationError("schema-1 receipts cannot contain shards")

    policy = _load_policy(policy_path)
    min_schema = policy.get("min_schema")
    if min_schema is not None and int(schema) < min_schema:
        raise VerificationError(
            f"receipt schema {schema} is below the policy minimum of {min_schema}"
        )
    toml = load_toml_defaults(root)
    repo, session, tests = _validate_structure(receipt, schema)
    signer = _verify_signature(receipt, schema, github_user_override, policy)
    if not receipt.get("signature"):
        if not allow_unsigned:
            raise VerificationError("receipt is unsigned")
        print("[gpu-proof] WARNING: accepting an unsigned receipt")
    else:
        print(f"[gpu-proof] Signature valid (signer: @{signer[0]})")

    required_mode = policy.get("require_mode")
    if required_mode is not None and receipt.get("mode") != required_mode:
        raise VerificationError(
            f"receipt mode {receipt.get('mode')!r} does not match required mode {required_mode!r}"
        )

    stored_fp = receipt["fingerprint"]
    if (
        not isinstance(stored_fp.get("digest"), str)
        or type(stored_fp.get("file_count")) is not int
        or stored_fp["file_count"] <= 0
    ):
        raise VerificationError("receipt fingerprint is empty or missing its digest")
    required_paths = policy.get("required_fingerprint_paths")
    if required_paths is not None and sorted(stored_fp.get("included_paths", [])) != sorted(required_paths):
        raise VerificationError("receipt fingerprint paths do not match repository policy")
    required_extras = policy.get("required_fingerprint_extra_paths")
    if required_extras is not None and sorted(stored_fp.get("extra_paths", [])) != sorted(required_extras):
        raise VerificationError("receipt fingerprint extra paths do not match repository policy")
    required_excluded = policy.get("required_fingerprint_excluded_paths")
    if required_excluded is not None and sorted(
        stored_fp.get("excluded_paths", [])
    ) != sorted(required_excluded):
        raise VerificationError("receipt fingerprint exclusions do not match repository policy")
    try:
        current_fp = recompute_fingerprint(stored_fp, root)
    except FingerprintError as exc:
        raise VerificationError(str(exc)) from exc
    if current_fp["digest"] != stored_fp["digest"] or current_fp["file_count"] != stored_fp["file_count"]:
        raise VerificationError("source fingerprint does not match the checked-out tree")
    print(f"[gpu-proof] Fingerprint OK ({current_fp['digest'][:12]}…)")

    stored_sha = repo["commit_sha"]
    if stored_sha != current_sha and not _is_ancestor(root, stored_sha, current_sha):
        raise VerificationError("receipt commit is not the current commit or an ancestor")
    print(f"[gpu-proof] Commit ancestry OK ({stored_sha[:12]}…)")

    allow_dirty = bool(policy.get("allow_dirty", schema in {"1", "2"}))
    # The receipt under verification is expected to sit in the tree (untracked
    # right after a run, or tracked-and-committed later); it must not count as
    # dirt, mirroring the recording-side exclusion.
    try:
        receipt_rel = (
            Path(receipt_path).resolve(strict=False).relative_to(Path(root).resolve()).as_posix()
        )
    except ValueError:
        receipt_rel = None
    dirty_exclusions = [receipt_rel] if receipt_rel else []
    try:
        current_dirty = is_dirty(root, required=True, exclude_paths=dirty_exclusions)
    except GitError as exc:
        raise VerificationError(str(exc)) from exc
    if not allow_dirty and (repo.get("dirty") or current_dirty):
        raise VerificationError("repository policy requires clean recording and verification trees")

    if schema in {"2", "3"} and "shards" in receipt:
        _verify_shards(receipt, root, policy)

    failed = [test["node_id"] for test in tests if test.get("outcome") not in {"passed", "skipped"}]
    if schema == "3" and session.get("outcome") != "passed":
        raise VerificationError("recorded pytest session did not pass")
    if failed:
        raise VerificationError(f"{len(failed)} recorded test(s) did not pass")
    for test in tests:
        bad_checks = [check for check in test.get("checks", []) if check.get("outcome") != "passed"]
        if bad_checks:
            raise VerificationError(f"test {test['node_id']!r} contains a failed comparison check")

    skipped = {test["node_id"] for test in tests if test.get("outcome") == "skipped"}
    if expected_skips_path is not None and allow_skipped:
        raise VerificationError("--expected-skips and --allow-skipped are mutually exclusive")
    if expected_skips_path is not None:
        expected = _load_node_ids(Path(expected_skips_path))
    elif not allow_skipped and toml.get("expected_skips"):
        expected = set(toml["expected_skips"])
    else:
        expected = None
    if expected is not None and skipped != expected:
        raise VerificationError("recorded skip set does not exactly match the expected baseline")
    if skipped and expected is None and not allow_skipped:
        raise VerificationError(f"{len(skipped)} marked test(s) were skipped")

    manifest = policy.get("required_test_manifest")
    if manifest:
        required_tests = _load_node_ids(Path(root) / manifest)
        if set(session["node_ids"]) != required_tests:
            raise VerificationError("recorded tests do not match the repository test manifest")

    if require_gpu is None:
        require_gpu = bool(toml.get("require_gpu", False))
    if require_gpu and not (receipt.get("environment") or {}).get("gpu_info"):
        raise VerificationError("repository policy requires recorded GPU information")

    max_days = (
        max_age_days_override
        if max_age_days_override is not None
        else policy.get("max_age_days", toml.get("max_age_days", 30))
    )
    if type(max_days) is not int or max_days < 0:
        raise VerificationError("max_age_days must be a non-negative integer")
    ended = _parse_time(session.get("ended_at"), "session.ended_at")
    age = datetime.datetime.now(datetime.UTC) - ended
    if age < datetime.timedelta(minutes=-5):
        raise VerificationError("receipt timestamp is in the future")
    if age > datetime.timedelta(days=max_days):
        raise VerificationError(f"receipt is older than the {max_days}-day policy")
    print(f"[gpu-proof] All {len(tests) - len(skipped)} executed test(s) passed")
    print("[gpu-proof] Receipt verified successfully.")


def _verify_shards(receipt: dict, root: str, policy: dict) -> None:
    shards = receipt.get("shards")
    if not isinstance(shards, list) or not shards:
        raise VerificationError("sharded receipt has no shards")
    test_ids = [test["node_id"] for test in receipt["tests"]]
    claimed: list[str] = []
    names: set[str] = set()
    required = policy.get("required_shard_fingerprints", {})
    for shard in shards:
        if not isinstance(shard, dict) or not isinstance(shard.get("name"), str):
            raise VerificationError("shard entry has no valid name")
        name = shard["name"]
        if name in names:
            raise VerificationError(f"duplicate shard name: {name!r}")
        names.add(name)
        ids = shard.get("node_ids")
        if not isinstance(ids, list) or len(ids) != len(set(ids)):
            raise VerificationError(f"shard {name!r} has invalid node_ids")
        if set(claimed) & set(ids):
            raise VerificationError(f"shard {name!r} overlaps another shard")
        claimed.extend(ids)
        fingerprint = shard.get("fingerprint")
        if not isinstance(fingerprint, dict):
            raise VerificationError(f"shard {name!r} has no fingerprint")
        if name in required:
            expected = required[name]
            if "paths" in expected and sorted(
                fingerprint.get("included_paths", [])
            ) != sorted(expected["paths"]):
                raise VerificationError(f"shard {name!r} paths do not match policy")
            if "extra_paths" in expected and sorted(
                fingerprint.get("extra_paths", [])
            ) != sorted(expected["extra_paths"]):
                raise VerificationError(f"shard {name!r} extra paths do not match policy")
            if "excluded_paths" in expected and sorted(
                fingerprint.get("excluded_paths", [])
            ) != sorted(expected["excluded_paths"]):
                raise VerificationError(f"shard {name!r} exclusions do not match policy")
        try:
            current = recompute_fingerprint(fingerprint, root)
        except FingerprintError as exc:
            raise VerificationError(f"shard {name!r}: {exc}") from exc
        if current["digest"] != fingerprint.get("digest"):
            raise VerificationError(f"shard {name!r} fingerprint does not match")
        carried = shard.get("carried")
        if carried:
            if not policy.get("allow_carried", False):
                raise VerificationError(f"shard {name!r} is carried but policy rejects carry-forward")
            if not isinstance(carried, dict):
                raise VerificationError(f"shard {name!r} carried metadata is invalid")
            original = _parse_time(carried.get("original_ended_at"), f"shard {name}.original_ended_at")
            age = datetime.datetime.now(datetime.UTC) - original
            limit = policy.get("carried_max_age_days", 30)
            if type(limit) is not int or limit < 0:
                raise VerificationError("carried_max_age_days must be a non-negative integer")
            if age < datetime.timedelta(minutes=-5) or age > datetime.timedelta(days=limit):
                raise VerificationError(f"carried shard {name!r} is outside its age policy")
    if claimed != test_ids:
        raise VerificationError("shard membership does not exactly partition tests[]")
    if required and set(required) != names:
        raise VerificationError("receipt shard set does not match repository policy")
