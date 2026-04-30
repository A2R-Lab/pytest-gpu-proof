"""
SSH-key-based signing and GitHub-key-based verification.

Signing uses the developer's existing SSH private key (the same key they use
to push to GitHub). Verification fetches the signer's public keys from
https://github.com/{username}.keys — no separate key distribution step needed.
"""

import base64
import hashlib
import os
from pathlib import Path
from typing import List, Optional
from urllib.request import urlopen

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDSA,
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.padding import MGF1, PSS
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_ssh_private_key,
    load_ssh_public_key,
)

from .base import SignerBase, VerifierError


def _discover_ssh_key() -> Optional[str]:
    from pytest_gpu_proof.gitutils import get_git_signing_key

    signing_key = get_git_signing_key()
    if signing_key and os.path.exists(signing_key):
        return signing_key

    home = Path.home()
    for candidate in ["id_ed25519", "id_ecdsa", "id_rsa"]:
        path = home / ".ssh" / candidate
        if path.exists():
            return str(path)

    return None


def _public_key_fingerprint(public_key) -> str:
    """SHA256 fingerprint matching `ssh-keygen -l -E sha256` output."""
    ssh_line = public_key.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    b64_part = ssh_line.split()[1]
    raw = base64.b64decode(b64_part)
    digest = hashlib.sha256(raw).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def _sign_with_key(private_key, data: bytes) -> bytes:
    if isinstance(private_key, Ed25519PrivateKey):
        return private_key.sign(data)
    if isinstance(private_key, EllipticCurvePrivateKey):
        return private_key.sign(data, ECDSA(SHA256()))
    if isinstance(private_key, RSAPrivateKey):
        return private_key.sign(
            data,
            PSS(mgf=MGF1(SHA256()), salt_length=PSS.MAX_LENGTH),
            SHA256(),
        )
    raise VerifierError(f"Unsupported private key type: {type(private_key).__name__}")


def _verify_with_key(public_key, signature: bytes, data: bytes) -> bool:
    try:
        if isinstance(public_key, Ed25519PublicKey):
            public_key.verify(signature, data)
        elif isinstance(public_key, EllipticCurvePublicKey):
            public_key.verify(signature, data, ECDSA(SHA256()))
        elif isinstance(public_key, RSAPublicKey):
            public_key.verify(
                signature,
                data,
                PSS(mgf=MGF1(SHA256()), salt_length=PSS.MAX_LENGTH),
                SHA256(),
            )
        else:
            return False
        return True
    except InvalidSignature:
        return False


def _parse_pubkey_line(line: str):
    parts = line.strip().split()
    if len(parts) < 2:
        return None
    try:
        return load_ssh_public_key(f"{parts[0]} {parts[1]}".encode())
    except Exception:
        return None


def fetch_github_public_keys(username: str) -> List:
    url = f"https://github.com/{username}.keys"
    try:
        with urlopen(url, timeout=10) as resp:
            content = resp.read().decode()
    except Exception as e:
        raise VerifierError(
            f"Could not fetch public keys for GitHub user {username!r}: {e}"
        )

    keys = [_parse_pubkey_line(line) for line in content.splitlines()]
    keys = [k for k in keys if k is not None]

    if not keys:
        raise VerifierError(
            f"No usable public keys found for GitHub user {username!r}. "
            "Ensure they have SSH keys registered at github.com/settings/keys."
        )
    return keys


def verify_with_github_keys(data: bytes, signature: bytes, github_username: str) -> bool:
    """Return True if signature was made by any SSH key the user has on GitHub."""
    keys = fetch_github_public_keys(github_username)
    return any(_verify_with_key(k, signature, data) for k in keys)


class SSHSigner(SignerBase):
    """Signs with the developer's SSH private key (same key used to push to GitHub)."""

    def __init__(self, key_path: Optional[str] = None):
        if key_path is None:
            key_path = _discover_ssh_key()
        if key_path is None:
            raise VerifierError(
                "No SSH private key found. Tried git config user.signingKey and "
                "~/.ssh/id_ed25519, ~/.ssh/id_ecdsa, ~/.ssh/id_rsa. "
                "Pass --gpu-proof-key=PATH to specify one explicitly."
            )

        self._key_path = key_path
        try:
            key_data = Path(key_path).read_bytes()
        except FileNotFoundError:
            raise VerifierError(f"No SSH private key found at {key_path}")

        try:
            self._private_key = load_ssh_private_key(key_data, password=None)
        except TypeError:
            import getpass
            pw = getpass.getpass(f"Passphrase for {key_path}: ").encode()
            self._private_key = load_ssh_private_key(key_data, password=pw)

        self._public_key = self._private_key.public_key()

    def sign(self, data: bytes) -> bytes:
        return _sign_with_key(self._private_key, data)

    def key_fingerprint(self) -> str:
        return _public_key_fingerprint(self._public_key)
