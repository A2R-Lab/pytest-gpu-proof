# Local Mode

Local mode is the default. It is the primary value proposition of this plugin:
run GPU tests on your own hardware, sign the receipt, let CI verify it.

## Prerequisites

- An SSH key registered on your GitHub account (`github.com/settings/keys`).
  This is the same key you use to push to GitHub — no new key needed.
- Your code in a git repository with a GitHub remote.

## Step-by-step

### 1. Install the plugin

```bash
pip install pytest-gpu-proof
```

### 2. Write tests using the fixture

```python
import pytest

@pytest.mark.gpu_proof
def test_rnea(gpu_proof_check):
    gpu_proof_check(
        name="rnea",
        reference=pinocchio_rnea,
        candidate=cuda_rnea,
        args=(model, q, qd, qdd),
        metadata={"robot": "go2", "algorithm": "rnea"},
    )
```

### 3. Run the tests locally (on your GPU machine)

```bash
pytest tests/ --gpu-proof-enable -v
```

The plugin:
- Runs every test normally.
- For tests that use `gpu_proof_check`, records the comparison outcome.
- At session end, detects your SSH key, computes a code fingerprint, and signs the receipt.
- Writes `gpu-proof.json` in the current directory.

Output:
```
...
[gpu-proof] Receipt written to gpu-proof.json
[gpu-proof] Signed with key SHA256:abc123...
```

### 4. Commit the receipt

```bash
git add gpu-proof.json
git commit -m "gpu proof receipt: update after rnea kernel fix"
git push
```

The receipt is a human-readable JSON file. It is safe to commit — it contains no secrets.

### 5. Add a CI verification step

```yaml
# .github/workflows/ci.yml
- name: Verify GPU proof receipt
  run: gpu-proof verify --receipt gpu-proof.json
```

No GPU, no secrets, no CUDA dependencies required in CI.

## Controlling which key is used

By default the plugin tries these in order:
1. `git config user.signingKey`
2. `~/.ssh/id_ed25519`
3. `~/.ssh/id_ecdsa`
4. `~/.ssh/id_rsa`

To specify explicitly:

```bash
pytest tests/ --gpu-proof-enable --gpu-proof-key=~/.ssh/my_key -v
```

## Controlling the fingerprint scope

By default the plugin fingerprints `src/` and `tests/`. To change this:

```bash
pytest tests/ --gpu-proof-enable --gpu-proof-fingerprint-paths=src,lib,tests -v
```

## What happens when the repo is dirty

The plugin records `"dirty": true` in the receipt but does not block signing.
The verifier warns about dirty receipts. You can enforce a clean-tree policy with
a policy file:

```yaml
# gpu-proof-policy.yaml
allow_dirty: false
max_age_days: 14
```

```bash
gpu-proof verify --receipt gpu-proof.json --policy gpu-proof-policy.yaml
```
