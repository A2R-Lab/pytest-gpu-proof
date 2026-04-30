import base64
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from pytest_gpu_proof.signers.ed25519 import (
    SSHSigner,
    _verify_with_key,
    _sign_with_key,
)


@pytest.fixture
def ssh_key_file(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    key_bytes = private_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    key_path = tmp_path / "id_ed25519"
    key_path.write_bytes(key_bytes)
    return key_path, private_key


def test_sign_and_verify_roundtrip(ssh_key_file):
    key_path, private_key = ssh_key_file
    signer = SSHSigner(key_path=str(key_path))

    data = b"hello gpu proof"
    sig = signer.sign(data)
    assert isinstance(sig, bytes)
    assert len(sig) == 64  # Ed25519 signature is always 64 bytes

    public_key = private_key.public_key()
    assert _verify_with_key(public_key, sig, data) is True


def test_verify_wrong_data_fails(ssh_key_file):
    key_path, private_key = ssh_key_file
    signer = SSHSigner(key_path=str(key_path))

    sig = signer.sign(b"correct data")
    assert _verify_with_key(private_key.public_key(), sig, b"wrong data") is False


def test_verify_wrong_key_fails(ssh_key_file):
    key_path, _ = ssh_key_file
    signer = SSHSigner(key_path=str(key_path))

    data = b"some data"
    sig = signer.sign(data)

    other_key = Ed25519PrivateKey.generate().public_key()
    assert _verify_with_key(other_key, sig, data) is False


def test_key_fingerprint_format(ssh_key_file):
    key_path, _ = ssh_key_file
    signer = SSHSigner(key_path=str(key_path))
    fp = signer.key_fingerprint()
    assert fp.startswith("SHA256:")
    assert len(fp) > 10


def test_missing_key_raises(tmp_path):
    from pytest_gpu_proof.signers.base import VerifierError
    with pytest.raises(VerifierError, match="No SSH private key found"):
        SSHSigner(key_path=str(tmp_path / "nonexistent"))
