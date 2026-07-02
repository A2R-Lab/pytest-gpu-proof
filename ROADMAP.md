# Roadmap

- **PyPI publishing (own session):** register the `pytest-gpu-proof` name, trusted
  publishing via GitHub Actions (OIDC), README as long_description, versioning +
  release discipline, CHANGELOG. Prereqs (CI, LICENSE, docs site, 3.11 floor)
  landed on `fixes-and-ci` 2026-07-02.
- SSHSIG-compatible signing (`ssh-keygen -Y verify` interop; agent-only + FIDO keys).
- CI-issued nonce / challenge mode for stronger replay protection.
