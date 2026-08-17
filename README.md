# pytest-gpu-proof

[![CI](https://github.com/A2R-Lab/pytest-gpu-proof/actions/workflows/ci.yml/badge.svg)](https://github.com/A2R-Lab/pytest-gpu-proof/actions/workflows/ci.yml)
[![Docs](https://github.com/A2R-Lab/pytest-gpu-proof/actions/workflows/docs.yml/badge.svg)](https://a2r-lab.github.io/pytest-gpu-proof/)
[![PyPI](https://img.shields.io/pypi/v/pytest-gpu-proof.svg)](https://pypi.org/project/pytest-gpu-proof/)
[![Python](https://img.shields.io/pypi/pyversions/pytest-gpu-proof.svg)](https://pypi.org/project/pytest-gpu-proof/)
[![Coverage: 100%](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/A2R-Lab/pytest-gpu-proof/actions/workflows/ci.yml)

Signed pytest receipts for local GPU runs, verified in CPU-only CI.

`pytest-gpu-proof` records which marked tests ran, their outcomes, the Git
commit and source fingerprint, the environment, and the run time. It signs
that payload with an existing SSH key. A normal CPU runner can then verify the
receipt against the signer's public keys on GitHub without rerunning CUDA.

This is a practical bridge for projects with local or lab GPUs but no
always-on GPU CI. It is signer attestation—not hardware attestation. See the
[security model](docs/security_model.md) before making stronger claims.

## The workflow

```text
GPU machine                              CPU-only CI
──────────────────────────────────       ───────────────────────────────
pytest --gpu-proof-enable                gpu-proof verify --receipt ...
  run marked tests                         validate schema and signature
  capture setup/call/teardown outcomes     fetch current GitHub SSH keys
  fingerprint the checked-out tree         recompute source fingerprint
  sign one schema-3 receipt                 enforce repository policy
```

The default signer policy is **open**: a valid receipt from any GitHub user is
accepted. This supports contributor-signed pull requests. Repositories that
only trust maintainers or dedicated CI keys can use **restricted** mode with
username and/or key-fingerprint allowlists.

## Install

```bash
python -m pip install pytest-gpu-proof
```

For development:

```bash
git clone https://github.com/A2R-Lab/pytest-gpu-proof.git
cd pytest-gpu-proof
python -m pip install -e ".[dev]"
```

Requirements: Python 3.11+, pytest 7+, and `cryptography` 41+.

## Quick start

Mark a test, or use the comparison fixture:

```python
import pytest


@pytest.mark.gpu_proof
def test_rnea(gpu_proof_check):
    gpu_proof_check(
        name="rnea",
        reference=python_rnea,
        candidate=cuda_rnea,
        args=(model, q, qd, qdd),
        metadata={"robot": "go2"},
    )
```

Run from the root of the project being attested:

```bash
pytest tests/gpu --gpu-proof-enable --gpu-proof-github-user YOUR_USER
gpu-proof verify --receipt gpu-proof.json --repo .
```

Commit `gpu-proof.json` with the code, then add a CPU-only CI step:

```yaml
- name: Verify local GPU test receipt
  run: gpu-proof verify --receipt gpu-proof.json --repo .
```

Receipt creation is fail-closed. A missing key, invalid Git state, empty
fingerprint scope, no selected tests, or write failure makes pytest fail and
leaves no stale receipt behind. `--gpu-proof-best-effort` is an explicit
development-only opt-out.

## Four interfaces

The project exposes four small interfaces:

1. **Markers** select receipt tests.
2. **`gpu_proof_check`** compares a reference callable with a candidate.
3. **`gpu-proof verify`** validates a receipt and repository policy.
4. **`gpu-proof merge`** combines separately executed shards and optionally
   carries unchanged shards forward.

### Markers

| Marker | Meaning |
|---|---|
| `@pytest.mark.gpu_proof` | Include the test in the receipt |
| `@pytest.mark.gpu_equivalence` | Alias for `gpu_proof` |
| `@pytest.mark.gpu_required` | Skip when neither `nvidia-smi` nor PyTorch reports a GPU |

Skipped tests are recorded. Verification rejects them by default. Prefer an
exact `--expected-skips` baseline over the broad `--allow-skipped` escape
hatch.

### Comparison fixture

```python
gpu_proof_check(
    name="operation",
    reference=reference_fn,
    candidate=gpu_fn,
    args=(arg1, arg2),
    kwargs={"option": value},
    compare=custom_compare,
    metadata={"case": "small"},
)
```

The default comparator is shape-safe: float/complex NumPy-compatible arrays
use `numpy.allclose(..., equal_nan=True)` and other arrays use exact equality.
Provide a comparator for GPU tensors, domain-specific tolerances, or structured
outputs. A comparator should return normally on success and raise
`AssertionError` on mismatch.

## Recording options

| Option | Default | Purpose |
|---|---:|---|
| `--gpu-proof-enable` | off | Enable receipt generation |
| `--gpu-proof-mode` | `local` | Record `local` or `ci-gpu` provenance |
| `--gpu-proof-out` | `gpu-proof.json` | Output artifact |
| `--gpu-proof-key` | discovered | SSH private-key file |
| `--gpu-proof-github-user` | discovered | GitHub account that owns the public key |
| `--gpu-proof-signing-backend` | `ed25519` | SSH signing, or explicit `none` |
| `--gpu-proof-required-marker` | `gpu_proof` | Custom receipt marker |
| `--gpu-proof-fail-on-skip` | off | Fail and suppress the receipt on selected skips |
| `--gpu-proof-fingerprint-paths` | `.` | Comma-separated Git-tracked scope |
| `--gpu-proof-fingerprint-extra-paths` | empty | Explicit ignored/generated inputs |
| `--gpu-proof-fingerprint-excluded-paths` | `gpu-proof.json` | Receipt artifacts omitted to avoid self-reference |
| `--gpu-proof-best-effort` | off | Warn instead of failing if emission fails |

Most defaults can live in the consumer's `pyproject.toml`:

```toml
[tool.gpu_proof]
mode = "local"
output = "gpu-proof.json"
fingerprint_paths = ["."]
fingerprint_extra_paths = ["generated/kernel_table.cuh"]
fingerprint_excluded_paths = ["gpu-proof.json"]
required_marker = "gpu_proof"
max_age_days = 30
require_gpu = true
```

By default, the fingerprint covers every tracked file in the repository,
including symlink targets and submodule gitlinks. Ignored/generated artifacts
are excluded unless explicitly named as extra paths. An empty or unreadable
scope is an error. The receipt artifact itself is excluded because a signed
file cannot hash its own final contents; set the exclusion explicitly if your
committed receipt uses a different path.

## Verification and policy

```bash
gpu-proof verify \
  --receipt gpu-proof.json \
  --repo . \
  --policy gpu-proof-policy.yaml
```

Schema-3 verification checks:

- strict receipt structure, complete test collection, and session outcome;
- signature, signed username, key fingerprint, and key algorithm;
- the signer's current public SSH keys at `github.com/<user>.keys`;
- tracked and explicit-extra source fingerprints;
- current/ancestor Git commit and clean recording/verification trees;
- test and comparison outcomes, exact skip policy, and optional test manifest;
- optional shard membership, shard fingerprints, and carry-forward policy;
- mode, GPU-information requirement, and freshness.

Open policy, suitable for contributor-signed PRs:

```yaml
signer_mode: open
max_age_days: 30
require_mode: local
required_fingerprint_paths: ["."]
required_fingerprint_excluded_paths: [gpu-proof.json]
required_test_manifest: gpu-proof-tests.txt
```

Restricted policy, suitable for a maintainer or CI allowlist:

```yaml
signer_mode: restricted
allowed_signers: [alice, release-bot]
allowed_key_fingerprints:
  - "SHA256:..."
max_age_days: 14
require_mode: ci-gpu
required_fingerprint_paths: ["."]
required_fingerprint_extra_paths: [generated/kernel_table.cuh]
required_fingerprint_excluded_paths: [gpu-proof.json]
allow_dirty: false
allow_carried: false
```

If both restricted allowlists are present, both must match. Unknown policy
fields fail verification so misspellings cannot silently weaken policy.
YAML support is available through `pytest-gpu-proof[yaml]`; JSON policy files
need no optional dependency.

`--allow-unsigned` accepts `"signature": null` with a loud warning. It removes
signer authentication and should not be used as a merge gate.

## Signing identity

The GitHub username is resolved in this order:

1. `--gpu-proof-github-user` or `github_username` configuration;
2. the authenticated `gh` CLI user;
3. the origin owner, with a warning because organization owners normally do
   not own an individual's SSH key.

The private-key file is resolved in this order:

1. `--gpu-proof-key`;
2. `git config user.signingKey`;
3. `~/.ssh/id_ed25519`, `id_ecdsa`, then `id_rsa`.

Ed25519, ECDSA, and RSA-PSS keys are supported. Agent-only and
hardware-backed keys are not yet supported because signing currently requires
a readable private-key file.

## Shards

Run shards as separate pytest processes; xdist workers are intentionally
rejected for receipt generation.

```bash
pytest tests/gpu/a --gpu-proof-enable \
  --gpu-proof-shard=a \
  --gpu-proof-shard-fingerprint-paths=src/a,tests/gpu/a \
  --gpu-proof-out=receipts/a.json

pytest tests/gpu/b --gpu-proof-enable \
  --gpu-proof-shard=b \
  --gpu-proof-shard-fingerprint-paths=src/b,tests/gpu/b \
  --gpu-proof-out=receipts/b.json

gpu-proof merge receipts/a.json receipts/b.json --out gpu-proof.json
```

The merger refuses mixed commits, schemas, global fingerprints, modes,
runtime environments, duplicate tests, and duplicate shard names. It records
input provenance but does not verify each input signature; the merger signs
for the union. See [sharding and carry-forward](docs/sharding.md).

## Receipt schema

New receipts use schema `"3"`. Signer identity is inside the signed payload,
test node IDs exactly match the recorded collection, setup and teardown
failures are terminal outcomes, and writes are atomic. The verifier retains
schema-1/2 compatibility, but their legacy defaults are less strict.

## Development

```bash
python -m pytest tests -q
coverage run -m pytest tests -q
coverage report --fail-under=100
mkdocs build --strict
python -m build
python -m twine check --strict dist/*
```

CI tests Python 3.11–3.13 and enforces 100% line and branch coverage. See
[CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and
[RELEASING.md](RELEASING.md).

## License

MIT.
