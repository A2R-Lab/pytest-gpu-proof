# Changelog

All notable changes to pytest-gpu-proof are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/); versions follow
[SemVer](https://semver.org/) (pre-1.0: minor bumps may break).

## [0.1.0] — 2026-07-07

First public release.

### Added
- pytest plugin (`-p` auto-loaded via the `pytest11` entry point): captures
  per-test outcomes and skips, git SHA, a SHA-256 source fingerprint over
  configured paths, and self-reported GPU info; emits a signed JSON receipt at
  session end (`--gpu-proof-enable`).
- Ed25519 SSH-key signing; signature covers the canonical (compact,
  sorted-key) JSON without the signature block. `none` backend for unsigned
  receipts.
- CPU-only verifier `gpu-proof verify`: signature against the signer's public
  `github.com/<user>.keys`, fingerprint match, commit SHA, outcome + skip
  policy, `--require-gpu`, freshness (`--max-age-days`, `0` = today only),
  dirty policy.
- Skip policies: `--allow-skipped` (any) or `--expected-skips FILE` (exact-set
  baseline — unexpected AND stale entries both fail); mutually exclusive.
  Also `[tool.gpu_proof] expected_skips`.
- Signer resolution: explicit flag/config → `gh` CLI login (keyholder) →
  origin-remote owner with a printed warning (org remotes have no SSH keys).
- `is_dirty` ignores untracked content inside submodules (pin moves and
  tracked edits still count).
- Receipt diffing (`compare.py`), `[tool.gpu_proof]` pyproject configuration,
  docs site (mkdocs), honest trust-model statement in
  `docs/security_model.md`.

[0.1.0]: https://github.com/A2R-Lab/pytest-gpu-proof/releases/tag/v0.1.0
