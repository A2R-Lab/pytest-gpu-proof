# Roadmap

- **PyPI publishing: infrastructure DONE 2026-07-07** — `publish.yml` (OIDC
  trusted publishing: TestPyPI on manual dispatch, PyPI on GitHub release),
  CHANGELOG.md, RELEASING.md, full metadata, wheel smoke-tested; name free on
  PyPI. REMAINING (repo-owner web UI, ~5 min, steps in RELEASING.md): add the
  pending trusted publishers on pypi.org + test.pypi.org and create the
  `pypi`/`testpypi` GitHub environments — then dispatch the TestPyPI lane and
  cut v0.1.0.
- SSHSIG-compatible signing (`ssh-keygen -Y verify` interop; agent-only + FIDO keys).
- CI-issued nonce / challenge mode for stronger replay protection.
