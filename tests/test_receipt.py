import base64
import json
import os
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from pytest_gpu_proof.receipt import (
    build_receipt_payload,
    canonicalize,
    finalize_receipt,
    write_receipt,
)
from pytest_gpu_proof.signers.ed25519 import SSHSigner


@pytest.fixture
def signer(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "id_ed25519"
    key_path.write_bytes(
        private_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    )
    return SSHSigner(key_path=str(key_path))


@pytest.fixture
def mock_config():
    from pytest_gpu_proof.config import GpuProofConfig
    return GpuProofConfig(
        enabled=True,
        mode="local",
        output="gpu-proof.json",
        fingerprint_paths=["src", "tests"],
    )


@pytest.fixture
def sample_test_results():
    return [
        {
            "node_id": "tests/test_foo.py::test_foo",
            "outcome": "passed",
            "duration_s": 0.1,
            "checks": [{"name": "relu", "outcome": "passed", "metadata": {}}],
        }
    ]


def test_canonicalize_is_deterministic():
    d = {"b": 2, "a": 1, "c": {"z": 26, "m": 13}}
    b1 = canonicalize(d)
    b2 = canonicalize(d)
    assert b1 == b2


def test_canonicalize_sorts_keys():
    d = {"z": 1, "a": 2}
    result = canonicalize(d).decode()
    assert result.index('"a"') < result.index('"z"')


def test_finalize_receipt_has_signature(mock_config, sample_test_results, signer, tmp_git_repo):
    os.chdir(tmp_git_repo)
    payload = build_receipt_payload(mock_config, sample_test_results, "2026-04-28T00:00:00Z", "2026-04-28T00:01:00Z")
    receipt = finalize_receipt(payload, signer)
    assert "signature" in receipt
    assert receipt["signature"]["algorithm"] == "ed25519"
    assert receipt["signature"]["value"]


def test_receipt_structure(mock_config, sample_test_results, signer, tmp_git_repo):
    os.chdir(tmp_git_repo)
    payload = build_receipt_payload(mock_config, sample_test_results, "2026-04-28T00:00:00Z", "2026-04-28T00:01:00Z")
    receipt = finalize_receipt(payload, signer)

    assert receipt["schema_version"] == "1"
    assert receipt["mode"] == "local"
    assert "repo" in receipt
    assert "fingerprint" in receipt
    assert "session" in receipt
    assert "tests" in receipt
    assert "environment" in receipt


def test_write_receipt(tmp_path, mock_config, sample_test_results, signer, tmp_git_repo):
    os.chdir(tmp_git_repo)
    payload = build_receipt_payload(mock_config, sample_test_results, "2026-04-28T00:00:00Z", "2026-04-28T00:01:00Z")
    receipt = finalize_receipt(payload, signer)
    out = tmp_path / "receipt.json"
    write_receipt(receipt, str(out))

    loaded = json.loads(out.read_text())
    assert loaded["schema_version"] == "1"
    assert "signature" in loaded


# ─── signer (github_username) resolution ────────────────────────────────────

def _build(mock_config, sample_test_results, tmp_git_repo):
    os.chdir(tmp_git_repo)
    return build_receipt_payload(
        mock_config, sample_test_results, "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z"
    )


def test_signer_uses_gh_cli_login_as_keyholder(
    monkeypatch, mock_config, sample_test_results, tmp_git_repo
):
    monkeypatch.setattr(
        "pytest_gpu_proof.receipt.get_gh_cli_login", lambda: "keyholder"
    )
    payload = _build(mock_config, sample_test_results, tmp_git_repo)
    assert payload["repo"]["github_username"] == "keyholder"


def test_signer_config_beats_gh_cli(
    monkeypatch, mock_config, sample_test_results, tmp_git_repo
):
    monkeypatch.setattr(
        "pytest_gpu_proof.receipt.get_gh_cli_login", lambda: "keyholder"
    )
    mock_config.github_username = "configured"
    payload = _build(mock_config, sample_test_results, tmp_git_repo)
    assert payload["repo"]["github_username"] == "configured"


def test_signer_remote_owner_fallback_warns(
    monkeypatch, capsys, mock_config, sample_test_results, tmp_git_repo
):
    # gh CLI unavailable (autouse fixture) and the origin remote is org-owned
    import subprocess
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:Some-Org/repo.git"],
        cwd=tmp_git_repo, check=True, capture_output=True,
    )
    payload = _build(mock_config, sample_test_results, tmp_git_repo)
    assert payload["repo"]["github_username"] == "Some-Org"
    assert "origin remote owner" in capsys.readouterr().out
