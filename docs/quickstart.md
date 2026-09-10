# Quickstart

## 1. Install

```bash
python -m pip install pytest-gpu-proof
```

Run the following commands from the root of the project whose code will be
attested. It must be a Git repository.

## 2. Select and compare a GPU test

```python
import numpy as np
import pytest


def compare(ref, candidate):
    np.testing.assert_allclose(candidate, ref, rtol=1e-5, atol=1e-6)


@pytest.mark.gpu_proof
@pytest.mark.gpu_required
def test_matmul(gpu_proof_check):
    gpu_proof_check(
        name="matmul",
        reference=numpy_matmul,
        candidate=cuda_matmul,
        args=(a, b),
        compare=compare,
        metadata={"dtype": "float32"},
    )
```

The fixture calls the reference and candidate with the same arguments. A
failed comparison fails pytest and is recorded. Plain marked tests are also
supported when comparison happens elsewhere.

## 3. Record

```bash
pytest tests/gpu \
  --gpu-proof-enable \
  --gpu-proof-github-user YOUR_GITHUB_USER
```

The command writes `gpu-proof.json` only after a complete selected collection
has a terminal outcome. Setup failures, teardown failures, selected skips, and
session failure are represented honestly.

By default every Git-tracked file is fingerprinted. If runtime behavior also
depends on generated or ignored inputs, name them explicitly:

```bash
pytest tests/gpu --gpu-proof-enable \
  --gpu-proof-fingerprint-extra-paths=generated/kernel_table.cuh
```

## 4. Verify locally

```bash
gpu-proof verify --receipt gpu-proof.json --repo .
```

Verification fetches the current public SSH keys for the signed GitHub user.
It then validates the signature, manifest, Git ancestry, clean-tree state,
complete outcomes, and freshness.

## 5. Commit and verify in CPU-only CI

```bash
git add gpu-proof.json
git commit -m "Record local GPU correctness receipt"
```

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
- run: pip install pytest-gpu-proof
- run: gpu-proof verify --receipt gpu-proof.json --repo .
```

For a repository trust policy:

```yaml
# gpu-proof-policy.yaml
signer_mode: open
max_age_days: 30
required_fingerprint_paths: ["."]
required_fingerprint_excluded_paths: [gpu-proof.json]
allow_dirty: false
```

```yaml
- run: gpu-proof verify --receipt gpu-proof.json --repo . --policy gpu-proof-policy.yaml
```

Continue with [local mode](local_mode.md), [policy](policy.md), or the bundled
CUDA examples in the repository's `examples/` directory.
