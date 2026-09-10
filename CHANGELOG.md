# Changelog

All notable changes to pytest-gpu-proof are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/); versions follow
[SemVer](https://semver.org/) (pre-1.0: minor bumps may break).

## [0.4.0] — 2026-08-17

### Added

- Schema `"3"`: signer username, key fingerprint, key algorithm, exact test
  collection, session outcome, pytest arguments, and per-shard environment/time
  are included in the signed payload.
- Open contributor and restricted signer policies. Restricted mode supports
  username and exact SSH-key-fingerprint allowlists.
- Policy pinning for mode, global tracked/extra fingerprint scope, exact test
  manifest, shard names, and per-shard tracked/extra scope.
- Explicit fingerprint paths for ignored/generated inputs and manifest support
  for symlinks and submodule gitlinks.
- Explicit receipt-artifact exclusions avoid self-referential whole-tree
  fingerprints and can be pinned by verification policy.
- `--gpu-proof-best-effort` as an explicit development escape hatch.
- `min_schema` policy field to refuse legacy schema-1/2 receipts.
- Python 3.13 CI, strict docs/package jobs, and enforced 100% line and branch
  coverage.

### Changed

- The default fingerprint scope is the entire Git-tracked repository instead
  of `src,tests`.
- Receipt creation now fails pytest on Git, fingerprint, key, serialization, or
  write errors; it also removes stale output at session start.
- Schema-3 verification rejects dirty recording and verification trees by
  default and accepts receipt commits only at the current commit or an ancestor.
- Setup/teardown failures, missing terminal reports, comparison exceptions,
  skipped tests, and overall session failure are represented and verified.
- GPU metadata records all devices reported by `nvidia-smi`.
- Array comparison is shape-safe, uses tolerance only for float/complex data,
  and uses exact equality for other dtypes.
- Receipt writes are atomic and strict JSON forbids NaN/non-JSON values.
- Receipt generation rejects xdist workers; use separate shard processes.
- Legacy schema-1/2 verification derives the policy-checked key fingerprint
  from the key that actually verified the signature; an asserted
  `signature.key_fingerprint` that disagrees is rejected.
- `signer_mode: restricted` policies reject unsigned receipts even with
  `--allow-unsigned`, and `--github-user` must match the signed schema-3
  identity.
- The receipt under verification is excluded from the verification-tree dirty
  check, so an untracked just-generated receipt verifies without gitignoring.
- Passphrase-protected SSH keys prompt correctly on current cryptography
  releases (`ValueError` as well as `TypeError`) and fail closed with an
  actionable message when no terminal is available.
- Uninitialized submodule checkouts fingerprint their index gitlink commit
  instead of accidentally recording the parent repository's HEAD.
- Receipt/shard age limits are enforced to the exact day boundary.
- GitHub usernames are validated before key fetches and key responses are
  size-capped.
- A stale receipt that cannot be cleared at session start raises a pytest
  usage error (an exit-status write that early would be silently overwritten).
- Merging receipts without session timestamps is refused with a clear error.

### Fixed

- Carry-forward now recomputes the stored fingerprint algorithm and preserves
  explicit generated/ignored shard inputs.
- Signed identity and algorithm substitution are rejected.
- Empty source scope, unmerged index entries, malformed policies, incomplete
  collections, and stale success artifacts fail closed.

## [0.3.0] — 2026-08-08

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

[0.1.0]: [ANONYMIZED-REPO-URL]
