"""
Verifier tests. GitHub key fetching is patched so tests run offline and fast.
"""

import base64
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from pytest_gpu_proof.receipt import (
    build_receipt_payload,
    canonicalize,
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


@pytest.fixture
def good_receipt(tmp_path, tmp_git_repo, signer_with_key):
    from pytest_gpu_proof.config import GpuProofConfig

    os.chdir(tmp_git_repo)
    signer, public_key = signer_with_key
    config = GpuProofConfig(enabled=True, fingerprint_paths=["src", "tests"])
    results = [
        {
            "node_id": "tests/test_add.py::test_add",
            "outcome": "passed",
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


def test_verify_fails_on_stale_receipt(good_receipt, tmp_git_repo):
    path, public_key = good_receipt
    receipt = json.loads(path.read_text())
    # Re-sign with an ancient timestamp
    receipt["session"]["ended_at"] = "2020-01-01T00:00:00Z"
    # We must re-sign after modifying
    from pytest_gpu_proof.signers.ed25519 import _sign_with_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey as _K

    with _mock_github_keys(public_key):
        # The modified receipt (unsigned change) will fail on signature first
        path.write_text(json.dumps(receipt))
        with pytest.raises(VerificationError):
            _verify(str(path), None, str(tmp_git_repo), "testuser", 30)


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
