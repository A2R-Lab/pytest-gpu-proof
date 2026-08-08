# Changelog

All notable changes to pytest-gpu-proof are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/); versions follow
[SemVer](https://semver.org/) (pre-1.0: minor bumps may break).

## [0.3.0] — unreleased

### Added
- Schema `"2"` sharded receipts: `--gpu-proof-shard NAME` +
  `--gpu-proof-shard-fingerprint-paths` emit a per-shard narrow fingerprint;
  `gpu-proof merge` unions schema-2 shards (unique names enforced).
- Verifiable carry-forward: `gpu-proof merge --carry-from OLD` grafts shards
  absent from the fresh inputs iff the old commit is an ancestor AND the
  shard's narrow fingerprint recomputes clean; grafted shards are marked
  `carried` and the verifier rejects them unless the policy sets
  `allow_carried: true` (bounded by `carried_max_age_days`, default 30).
- Verifier: schema-2 checks (per-shard fingerprint recompute, membership
  partition of `tests[]`, carried-shard policy gate). Schema-1 receipts are
  unchanged and a schema-1 receipt carrying a `shards` block is rejected.

## [0.2.0] — 2026-08-07

### Added
- `gpu-proof merge`: union N shard receipts from one commit into a single
  re-signed receipt (per-module crash isolation / machine sharding). Refuses
  shards that disagree on schema, commit SHA, fingerprint, mode, or
  environment; duplicate node IDs across shards are a hard error. Records
  per-shard provenance under `session.shards` (additive — the verifier is
  unchanged). `repo.dirty` is OR-ed; `gpu_info` survives CPU-only shards.
  Docs: `docs/sharding.md`.

### Fixed
- Explicit CLI values equal to their built-in defaults are no longer silently
  ignored in favor of `[tool.gpu_proof]` (value-taking options now register a
  `None` sentinel; `--gpu-proof-fail-on-skip` ORs with the toml value since a
  store_true flag can only turn it on).

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
