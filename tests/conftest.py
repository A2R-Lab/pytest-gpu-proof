import base64
import json
import os
import tempfile
import subprocess

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


@pytest.fixture(autouse=True)
def _pytester_git_repo(request):
    """Receipt-emission integration tests run in a real, committed git tree."""
    if "pytester" not in request.fixturenames:
        return
    pytester = request.getfixturevalue("pytester")
    subprocess.run(["git", "init", "-q"], cwd=pytester.path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=pytester.path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=pytester.path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:testuser/example.git"],
        cwd=pytester.path,
        check=True,
    )
    (pytester.path / ".gitkeep").write_text("")
    subprocess.run(["git", "add", ".gitkeep"], cwd=pytester.path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=pytester.path, check=True)


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
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:testuser/example.git"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    (tmp_path / ".git" / "info" / "exclude").write_text(
        "*.json\nid_*\nexpected_skips.txt\npyproject.toml\n"
    )
    return tmp_path
