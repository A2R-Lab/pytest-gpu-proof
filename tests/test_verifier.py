"""
Verifier tests. GitHub key fetching is patched so tests run offline and fast.
"""

import datetime
import json
import os
import sys
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from pytest_gpu_proof.receipt import (
    build_receipt_payload,
    finalize_receipt,
    write_receipt,
)
from pytest_gpu_proof.signers.ed25519 import SSHSigner, _verify_with_key
from pytest_gpu_proof.verify import VerificationError, _verify


@pytest.fixture
def keypair():
    pk = Ed25519PrivateKey.generate()
    return pk, pk.public_key()


@pytest.fixture
def signer_with_key(tmp_path, keypair):
    private_key, public_key = keypair
    key_path = tmp_path / "id_ed25519"
    key_path.write_bytes(
        private_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    )
    return SSHSigner(key_path=str(key_path)), public_key


def _utcstamp(days_ago: int = 0) -> str:
    ts = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_receipt(
    tmp_path,
    tmp_git_repo,
    signer,
    results=None,
    ended_at=None,
    mutate=None,
    sign=True,
):
    """Build a receipt against tmp_git_repo, optionally mutating the payload
    *before* signing (so the signature stays valid)."""
    from pytest_gpu_proof.config import GpuProofConfig

    os.chdir(tmp_git_repo)
    config = GpuProofConfig(enabled=True, fingerprint_paths=["src", "tests"])
    results = results or [
        {
            "node_id": "tests/test_add.py::test_add",
            "outcome": "passed",
            "duration_s": 0.01,
            "checks": [],
        }
    ]
    now = _utcstamp()
    payload = build_receipt_payload(config, results, now, ended_at or now)
    if mutate is not None:
        mutate(payload)
    if sign:
        receipt = finalize_receipt(payload, signer)
    else:
        receipt = dict(payload)
        receipt["signature"] = None
    path = tmp_path / "gpu-proof.json"
    write_receipt(receipt, str(path))
    return path


@pytest.fixture
def good_receipt(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer)
    return path, public_key


def _mock_github_keys(public_key):
    """Return a patcher that makes verify_with_github_keys use our local public key."""
    def _fake_verify(data, signature, username):
        return _verify_with_key(public_key, signature, data)

    return patch(
        "pytest_gpu_proof.verify.verify_with_github_keys",
        side_effect=_fake_verify,
    )


def test_verify_passes(good_receipt, tmp_git_repo):
    path, public_key = good_receipt
    with _mock_github_keys(public_key):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_verify_passes_when_receipt_is_committed_after_code(good_receipt, tmp_git_repo):
    path, public_key = good_receipt
    receipt_path = tmp_git_repo / "gpu-proof.json"
    receipt_path.write_text(path.read_text())

    import subprocess

    subprocess.run(["git", "add", "gpu-proof.json"], cwd=tmp_git_repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add GPU proof receipt"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
    )

    with _mock_github_keys(public_key):
        _verify(str(receipt_path), None, str(tmp_git_repo), "testuser", None)


def test_verify_fails_on_bad_signature(good_receipt, tmp_git_repo):
    path, _ = good_receipt
    other_key = Ed25519PrivateKey.generate().public_key()
    with _mock_github_keys(other_key):
        with pytest.raises(VerificationError, match="Signature does not match"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_verify_fails_on_modified_receipt(good_receipt, tmp_git_repo):
    path, public_key = good_receipt
    receipt = json.loads(path.read_text())
    receipt["tests"][0]["outcome"] = "failed"
    path.write_text(json.dumps(receipt))

    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="Signature does not match"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_verify_fails_on_stale_receipt(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    # Genuinely-signed receipt whose ended_at is far in the past: every check
    # up to freshness must pass, and freshness must be the one that fails.
    path = _make_receipt(
        tmp_path, tmp_git_repo, signer, ended_at="2020-01-01T00:00:00Z"
    )
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match=r"days old; policy allows max 30"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", 30)


def test_verify_max_age_zero_is_respected(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer, ended_at=_utcstamp(days_ago=5))
    with _mock_github_keys(public_key):
        # An explicit override of 0 must not silently fall back to 30.
        with pytest.raises(VerificationError, match=r"policy allows max 0"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", 0)


def test_verify_rejects_unsigned_receipt(tmp_path, tmp_git_repo, signer_with_key):
    signer, _ = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer, sign=False)
    with pytest.raises(VerificationError, match="UNSIGNED"):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_verify_accepts_unsigned_receipt_with_allow_unsigned(
    tmp_path, tmp_git_repo, signer_with_key
):
    signer, _ = signer_with_key
    path = _make_receipt(tmp_path, tmp_git_repo, signer, sign=False)
    _verify(str(path), None, str(tmp_git_repo), "testuser", None, allow_unsigned=True)


def test_verify_rejects_skipped_tests(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key
    results = [
        {"node_id": "tests/test_add.py::test_add", "outcome": "passed",
         "duration_s": 0.01, "checks": []},
        {"node_id": "tests/test_add.py::test_skipped", "outcome": "skipped",
         "duration_s": 0.0, "checks": []},
    ]
    path = _make_receipt(tmp_path, tmp_git_repo, signer, results=results)
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="skipped"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)
        # Explicit opt-in accepts them.
        _verify(
            str(path), None, str(tmp_git_repo), "testuser", None, allow_skipped=True
        )


def test_verify_missing_digest_raises_clean_error(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key

    def drop_digest(payload):
        del payload["fingerprint"]["digest"]

    path = _make_receipt(tmp_path, tmp_git_repo, signer, mutate=drop_digest)
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="missing its digest"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_yaml_policy_without_pyyaml_raises(tmp_path, monkeypatch):
    from pytest_gpu_proof.verify import _load_policy

    policy = tmp_path / "policy.yaml"
    policy.write_text("max_age_days: 7\n")
    monkeypatch.setitem(sys.modules, "yaml", None)  # force ImportError
    with pytest.raises(VerificationError, match="PyYAML"):
        _load_policy(str(policy))


def test_json_policy_works_without_pyyaml(tmp_path, monkeypatch):
    from pytest_gpu_proof.verify import _load_policy

    policy = tmp_path / "policy.json"
    policy.write_text('{"max_age_days": 7}')
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert _load_policy(str(policy)) == {"max_age_days": 7}


def test_require_gpu_rejects_null_gpu_info(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key

    def null_gpu(payload):
        payload["environment"]["gpu_info"] = None

    path = _make_receipt(tmp_path, tmp_git_repo, signer, mutate=null_gpu)
    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="gpu_info"):
            _verify(
                str(path), None, str(tmp_git_repo), "testuser", None, require_gpu=True
            )
        # Off by default: same receipt verifies fine.
        _verify(str(path), None, str(tmp_git_repo), "testuser", None)


def test_require_gpu_accepts_present_gpu_info(tmp_path, tmp_git_repo, signer_with_key):
    signer, public_key = signer_with_key

    def fake_gpu(payload):
        payload["environment"]["gpu_info"] = {
            "name": "NVIDIA Test GPU",
            "driver_version": "555.0",
            "memory": "8192 MiB",
        }

    path = _make_receipt(tmp_path, tmp_git_repo, signer, mutate=fake_gpu)
    with _mock_github_keys(public_key):
        _verify(str(path), None, str(tmp_git_repo), "testuser", None, require_gpu=True)


def test_verify_fails_on_failed_test(tmp_path, tmp_git_repo, signer_with_key):
    from pytest_gpu_proof.config import GpuProofConfig

    os.chdir(tmp_git_repo)
    signer, public_key = signer_with_key
    config = GpuProofConfig(enabled=True, fingerprint_paths=["src", "tests"])
    results = [
        {
            "node_id": "tests/test_add.py::test_add",
            "outcome": "failed",
            "duration_s": 0.01,
            "checks": [],
        }
    ]
    import datetime
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = build_receipt_payload(config, results, now, now)
    receipt = finalize_receipt(payload, signer)
    path = tmp_path / "gpu-proof.json"
    write_receipt(receipt, str(path))

    with _mock_github_keys(public_key):
        with pytest.raises(VerificationError, match="did not pass"):
            _verify(str(path), None, str(tmp_git_repo), "testuser", None)
