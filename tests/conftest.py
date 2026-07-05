import base64
import json
import os
import tempfile

import pytest

pytest_plugins = ["pytester"]
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


@pytest.fixture(autouse=True)
def _no_gh_cli(monkeypatch):
    """Keep the suite hermetic: never shell out to `gh` for the signer login.

    On a developer box with an authenticated gh CLI, receipt building would
    otherwise hit the network. Signer-resolution tests re-patch explicitly.
    """
    monkeypatch.setattr(
        "pytest_gpu_proof.receipt.get_gh_cli_login", lambda: None
    )


@pytest.fixture
def ed25519_keypair():
    """Fresh Ed25519 keypair for testing — no disk I/O, no real SSH keys needed."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def tmp_git_repo(tmp_path):
    """Minimal git repo with a couple of tracked files."""
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "mymodule.py").write_text("def add(a, b): return a + b\n")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_add.py").write_text("def test_add(): assert 1+1==2\n")

    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path
