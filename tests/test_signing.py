import base64
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from pytest_gpu_proof.signers.ed25519 import (
    SSHSigner,
    _discover_ssh_key,
    _parse_pubkey_line,
    fetch_github_public_keys,
    find_verifying_github_key,
    public_key_algorithm,
    verify_with_github_keys,
    _verify_with_key,
    _sign_with_key,
)
from pytest_gpu_proof.signers.base import VerifierError


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


def test_algorithm_derived_from_key_type(ssh_key_file, tmp_path):
    key_path, _ = ssh_key_file
    assert SSHSigner(key_path=str(key_path)).algorithm() == "ed25519"

    from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key

    ec_key = generate_private_key(SECP256R1())
    ec_path = tmp_path / "id_ecdsa"
    ec_path.write_bytes(
        ec_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    )
    assert SSHSigner(key_path=str(ec_path)).algorithm() == "ecdsa-sha256"


def test_ecdsa_and_rsa_roundtrips(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
    from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key as rsa_key

    for key in (generate_private_key(SECP256R1()), rsa_key(public_exponent=65537, key_size=2048)):
        path = tmp_path / f"key-{type(key).__name__}"
        path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()))
        signer = SSHSigner(str(path))
        signature = signer.sign(b"payload")
        assert _verify_with_key(key.public_key(), signature, b"payload")
        assert signer.algorithm() in {"ecdsa-sha256", "rsa-pss-sha256"}


def test_unsupported_key_types_are_rejected():
    with pytest.raises(VerifierError, match="Unsupported public"):
        public_key_algorithm(object())
    with pytest.raises(VerifierError, match="Unsupported private"):
        _sign_with_key(object(), b"data")
    assert _verify_with_key(object(), b"sig", b"data") is False


def test_receipt_algorithm_matches_key(ssh_key_file):
    from pytest_gpu_proof.receipt import finalize_receipt

    key_path, _ = ssh_key_file
    signer = SSHSigner(key_path=str(key_path))
    receipt = finalize_receipt({"schema_version": "3", "repo": {}, "tests": []}, signer)
    assert receipt["signer"]["algorithm"] == "ed25519"


def test_missing_key_raises(tmp_path):
    with pytest.raises(VerifierError, match="No SSH private key found"):
        SSHSigner(key_path=str(tmp_path / "nonexistent"))


def test_key_discovery_prefers_git_signing_key(monkeypatch, ssh_key_file):
    key_path, _ = ssh_key_file
    monkeypatch.setattr(
        "pytest_gpu_proof.gitutils.get_git_signing_key", lambda root: str(key_path)
    )
    assert _discover_ssh_key("repo") == str(key_path)


def test_key_discovery_home_candidates_and_none(monkeypatch, tmp_path):
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    candidate = ssh / "id_rsa"
    candidate.write_text("placeholder")
    monkeypatch.setattr("pytest_gpu_proof.gitutils.get_git_signing_key", lambda root: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert _discover_ssh_key() == str(candidate)
    candidate.unlink()
    assert _discover_ssh_key() is None


def test_signer_automatic_discovery_and_failure(monkeypatch, ssh_key_file):
    key_path, _ = ssh_key_file
    monkeypatch.setattr(
        "pytest_gpu_proof.signers.ed25519._discover_ssh_key", lambda root: str(key_path)
    )
    assert SSHSigner(root="repo").sign(b"x")
    monkeypatch.setattr(
        "pytest_gpu_proof.signers.ed25519._discover_ssh_key", lambda root: None
    )
    with pytest.raises(VerifierError, match="No SSH private key found"):
        SSHSigner(root="repo")


def test_encrypted_private_key_prompts(monkeypatch, tmp_path):
    private_key = Ed25519PrivateKey.generate()
    path = tmp_path / "encrypted"
    path.write_bytes(b"encrypted-placeholder")
    calls = []

    def load(data, password):
        calls.append(password)
        if password is None:
            raise TypeError("encrypted")
        assert password == b"secret"
        return private_key

    monkeypatch.setattr("pytest_gpu_proof.signers.ed25519.load_ssh_private_key", load)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "secret")
    assert SSHSigner(str(path)).sign(b"x")
    assert calls == [None, b"secret"]


def test_encrypted_key_valueerror_also_prompts(monkeypatch, tmp_path):
    """cryptography >= 41 raises ValueError (not TypeError) for
    passphrase-protected OpenSSH keys; the prompt fallback must cover both.
    (Real encrypted-key round-trips need bcrypt, so this stays mocked.)"""
    private_key = Ed25519PrivateKey.generate()
    path = tmp_path / "encrypted"
    path.write_bytes(b"encrypted-placeholder")

    def load(data, password):
        if password is None:
            raise ValueError("Key is password-protected.")
        assert password == b"secret"
        return private_key

    monkeypatch.setattr("pytest_gpu_proof.signers.ed25519.load_ssh_private_key", load)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "secret")
    assert SSHSigner(str(path)).sign(b"x")


def test_encrypted_key_without_terminal_fails_closed(monkeypatch, tmp_path):
    path = tmp_path / "encrypted"
    path.write_bytes(b"encrypted-placeholder")

    def load(data, password):
        raise ValueError("Key is password-protected.")

    monkeypatch.setattr("pytest_gpu_proof.signers.ed25519.load_ssh_private_key", load)

    def no_tty(prompt):
        raise EOFError("no terminal")

    monkeypatch.setattr("getpass.getpass", no_tty)
    with pytest.raises(VerifierError, match="Could not load SSH private key"):
        SSHSigner(str(path))

    # Wrong passphrase also surfaces as the actionable signer error.
    monkeypatch.setattr("getpass.getpass", lambda prompt: "wrong")
    with pytest.raises(VerifierError, match="Could not load SSH private key"):
        SSHSigner(str(path))


def test_fetch_rejects_invalid_github_username():
    with pytest.raises(VerifierError, match="invalid GitHub username"):
        fetch_github_public_keys("../evil?path")


def test_parse_and_fetch_github_keys(monkeypatch, ssh_key_file):
    _, private_key = ssh_key_file
    public_line = private_key.public_key().public_bytes(
        Encoding.OpenSSH, PublicFormat.OpenSSH
    ).decode()
    assert _parse_pubkey_line("bad") is None
    assert _parse_pubkey_line("ssh-bad !!!") is None
    assert _parse_pubkey_line(public_line)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=None):
            return f"bad\n{public_line} comment\n".encode()

    monkeypatch.setattr("pytest_gpu_proof.signers.ed25519.urlopen", lambda *a, **k: Response())
    keys = fetch_github_public_keys("alice")
    signature = _sign_with_key(private_key, b"payload")
    assert verify_with_github_keys(b"payload", signature, "alice")
    assert find_verifying_github_key(b"payload", signature, "alice") is not None
    assert find_verifying_github_key(b"wrong", signature, "alice") is None


def test_fetch_github_keys_errors(monkeypatch):
    def network_error(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("pytest_gpu_proof.signers.ed25519.urlopen", network_error)
    with pytest.raises(VerifierError, match="Could not fetch"):
        fetch_github_public_keys("alice")

    class Empty:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=None):
            return b"not-a-key\n"

    monkeypatch.setattr("pytest_gpu_proof.signers.ed25519.urlopen", lambda *a, **k: Empty())
    with pytest.raises(VerifierError, match="No usable"):
        fetch_github_public_keys("alice")
