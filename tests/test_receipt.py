import base64
import json
import os
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from pytest_gpu_proof.receipt import (
    _env_info,
    _gpu_info,
    _resolve_github_username,
    _utcnow,
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


@pytest.mark.parametrize("value", [{"bad": float("nan")}, {"bad": object()}])
def test_canonicalize_rejects_non_json_values(value):
    with pytest.raises(ValueError, match="non-JSON"):
        canonicalize(value)


def test_environment_and_gpu_capture(monkeypatch):
    import subprocess

    result = subprocess.CompletedProcess(
        [],
        0,
        stdout=(
            "0, GPU-1, Ada, 555.1, 24564 MiB, 8.9\n"
            "1, GPU-2, Hopper\n"
        ),
        stderr="",
    )
    monkeypatch.setattr("pytest_gpu_proof.receipt.subprocess.run", lambda *a, **k: result)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    info = _gpu_info()
    assert len(info["devices"]) == 2
    assert info["devices"][1]["driver_version"] is None
    assert info["cuda_visible_devices"] == "1"
    assert _env_info()["gpu_info"] == info
    assert _utcnow().endswith("Z")


@pytest.mark.parametrize(
    "behavior",
    [
        lambda: __import__("subprocess").CompletedProcess([], 1, stdout="", stderr="bad"),
        lambda: (_ for _ in ()).throw(FileNotFoundError()),
        lambda: (_ for _ in ()).throw(__import__("subprocess").TimeoutExpired("nvidia-smi", 10)),
    ],
)
def test_gpu_capture_unavailable(monkeypatch, behavior):
    monkeypatch.setattr(
        "pytest_gpu_proof.receipt.subprocess.run", lambda *a, **k: behavior()
    )
    assert _gpu_info() is None


def test_finalize_receipt_has_signature(mock_config, sample_test_results, signer, tmp_git_repo):
    os.chdir(tmp_git_repo)
    payload = build_receipt_payload(mock_config, sample_test_results, "2026-04-28T00:00:00Z", "2026-04-28T00:01:00Z")
    receipt = finalize_receipt(payload, signer)
    assert "signature" in receipt
    assert receipt["signer"]["algorithm"] == "ed25519"
    assert set(receipt["signature"]) == {"value"}
    assert receipt["signature"]["value"]


def test_receipt_structure(mock_config, sample_test_results, signer, tmp_git_repo):
    os.chdir(tmp_git_repo)
    payload = build_receipt_payload(mock_config, sample_test_results, "2026-04-28T00:00:00Z", "2026-04-28T00:01:00Z")
    receipt = finalize_receipt(payload, signer)

    assert receipt["schema_version"] == "3"
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
    assert loaded["schema_version"] == "3"
    assert "signature" in loaded


def test_write_receipt_cleans_temporary_after_replace_error(tmp_path, monkeypatch):
    monkeypatch.setattr("pytest_gpu_proof.receipt.os.replace", lambda *a: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(OSError, match="no"):
        write_receipt({"ok": True}, str(tmp_path / "receipt.json"))
    assert list(tmp_path.iterdir()) == []


def test_legacy_finalize_shape(signer):
    receipt = finalize_receipt(
        {"schema_version": "2", "repo": {"github_username": "alice"}}, signer
    )
    assert receipt["signature"]["signer"] == "alice"
    assert receipt["signature"]["algorithm"] == "ed25519"


def test_duplicate_collected_node_ids_rejected(
    mock_config, sample_test_results, tmp_git_repo
):
    mock_config.repo_root = str(tmp_git_repo)
    with pytest.raises(ValueError, match="not unique"):
        build_receipt_payload(
            mock_config,
            sample_test_results,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:01Z",
            collected_node_ids=["same", "same"],
        )


def test_shard_extra_paths_fall_back_to_global(
    mock_config, sample_test_results, tmp_git_repo
):
    extra = tmp_git_repo / "generated.bin"
    extra.write_bytes(b"generated")
    mock_config.repo_root = str(tmp_git_repo)
    mock_config.fingerprint_extra_paths = ["generated.bin"]
    mock_config.shard_name = "core"
    payload = build_receipt_payload(
        mock_config,
        sample_test_results,
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:01Z",
        override_github_username="alice",
    )
    assert payload["shards"][0]["fingerprint"]["extra_paths"] == ["generated.bin"]


def test_explicit_empty_shard_extras_override_global(
    mock_config, sample_test_results, tmp_git_repo
):
    extra = tmp_git_repo / "generated.bin"
    extra.write_bytes(b"generated")
    mock_config.repo_root = str(tmp_git_repo)
    mock_config.fingerprint_extra_paths = ["generated.bin"]
    mock_config.shard_name = "core"
    mock_config.shard_fingerprint_extra_paths = []
    payload = build_receipt_payload(
        mock_config,
        sample_test_results,
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:01Z",
        override_github_username="alice",
    )
    assert payload["shards"][0]["fingerprint"]["extra_paths"] == []


def test_recording_ignores_only_tracked_output_dirtiness(
    mock_config, sample_test_results, tmp_git_repo
):
    import subprocess

    receipt = tmp_git_repo / "gpu-proof.json"
    receipt.write_text("old\n")
    subprocess.run(["git", "add", "-f", "gpu-proof.json"], cwd=tmp_git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "receipt"], cwd=tmp_git_repo, check=True, capture_output=True)
    receipt.unlink()
    mock_config.repo_root = str(tmp_git_repo)
    mock_config.output = str(receipt)
    payload = build_receipt_payload(
        mock_config,
        sample_test_results,
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:01Z",
        override_github_username="alice",
    )
    assert payload["repo"]["dirty"] is False


def test_output_outside_repo_is_not_a_dirty_exclusion(
    mock_config, sample_test_results, tmp_git_repo
):
    mock_config.repo_root = str(tmp_git_repo)
    mock_config.output = str(tmp_git_repo.parent / "outside" / "receipt.json")
    payload = build_receipt_payload(
        mock_config,
        sample_test_results,
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:01Z",
        override_github_username="alice",
    )
    assert payload["repo"]["dirty"] is False


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
        ["git", "remote", "set-url", "origin", "git@github.com:Some-Org/repo.git"],
        cwd=tmp_git_repo, check=True, capture_output=True,
    )
    payload = _build(mock_config, sample_test_results, tmp_git_repo)
    assert payload["repo"]["github_username"] == "Some-Org"
    assert "origin owner" in capsys.readouterr().out


def test_signer_resolution_failure(monkeypatch, mock_config):
    monkeypatch.setattr("pytest_gpu_proof.receipt.get_gh_cli_login", lambda: None)
    monkeypatch.setattr("pytest_gpu_proof.receipt.get_github_username", lambda root: None)
    with pytest.raises(ValueError, match="cannot determine"):
        _resolve_github_username(mock_config, None, ".")
