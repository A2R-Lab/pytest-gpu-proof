# pytest-gpu-proof

A pytest plugin that lets you run GPU equivalence tests locally, sign the results with your existing SSH key, and have GitHub Actions verify the receipt — **without re-running the GPU tests in CI**.

The trust model is simple: if you can push to GitHub, you can sign a receipt. Verification fetches your public keys from `github.com/{username}.keys`, exactly as SSH does.

> **Requirements:** Python 3.11+ · pytest 7.0+ · cryptography 41.0+
> The package is not yet on PyPI — install from source with `pip install -e .` (see [Installation](#installation)).

---

## Why this exists

GPU CI is expensive. For many teams, the typical workflow is:

1. Run GPU correctness tests locally (or on a lab machine).
2. Push code and let CI run only CPU tests.
3. Hope the GPU tests still pass.

This plugin closes that gap by producing a **cryptographically signed receipt** that proves a specific person ran specific tests against specific code at a specific time — verifiable in ordinary CPU-only CI with no GPU and no secrets.

---

## How it works

```
Local machine (GPU)               GitHub Actions (CPU only)
─────────────────────────────     ──────────────────────────────────────
pytest --gpu-proof-enable  →  →   gpu-proof verify --receipt gpu-proof.json
  runs your GPU tests              fetches your public keys from
  computes code fingerprint          github.com/{you}.keys
  signs receipt with SSH key       verifies signature + fingerprint
  writes gpu-proof.json            exits 0 (pass) or 1 (fail)
```

**Zero new key management.** The plugin uses the SSH key you already have in `~/.ssh/` (the same one you use to push to GitHub). Your public key is already on GitHub. The verifier reads it from there.

---

## Installation

The package is not yet published to PyPI. Install from a local clone:

```bash
git clone <this-repo>
cd pytest-gpu-proof
pip install -e .          # base install (pytest + cryptography)
pip install -e ".[dev]"   # also installs numpy, pytest-cov
```

Or use the helper script (checks your Python version first):

```bash
bash install.sh          # base install
bash install.sh dev      # dev install
```

Once the package is registered on PyPI, you will be able to install it with:

```bash
pip install pytest-gpu-proof   # not yet available
```

---

## Quick start

### Step 1 — Install from source

```bash
git clone <this-repo>
cd pytest-gpu-proof
pip install -e .
```

### Step 2 — Run the bundled demo (no GPU needed)

The repo includes a no-GPU demo that works on any machine:

```bash
cd examples/minimal_python_only
pytest test_minimal.py --gpu-proof-enable -v
```

Expected output:
```
PASSED test_minimal.py::test_relu
PASSED test_minimal.py::test_softmax
...
[gpu-proof] Receipt written to gpu-proof.json
[gpu-proof] Signed with key SHA256:...
```

### Step 3 — Verify the receipt

```bash
gpu-proof verify --receipt gpu-proof.json
```

The verifier fetches your public keys from `github.com/{you}.keys` automatically — no secrets needed.

### Step 4 — Use it in your own project

Add the marker and fixture to your tests:

```python
import pytest

@pytest.mark.gpu_proof
def test_my_kernel(gpu_proof_check):
    gpu_proof_check(
        name="relu",
        reference=python_relu,     # your reference implementation
        candidate=cuda_relu,       # your GPU wrapper
        args=([1.0, -2.0, 3.0],),
        metadata={"kernel": "relu"},
    )
```

Run from **your project's root** (not the pytest-gpu-proof source directory):

```bash
pytest path/to/your/tests/ --gpu-proof-enable -v
# → writes gpu-proof.json in the current directory
```

> **Note:** The `--gpu-proof-enable` flag only writes a receipt if at least one test is marked with `@pytest.mark.gpu_proof` or uses the `gpu_proof_check` fixture. Running it against the plugin's own `tests/` directory (which tests the plugin internals) will not produce a receipt.

### Step 5 — Commit and verify in CI

```bash
git add gpu-proof.json
git commit -m "update GPU proof receipt"
git push
```

```yaml
# .github/workflows/ci.yml
- name: Verify GPU proof
  run: gpu-proof verify --receipt gpu-proof.json
```

---

## The `gpu_proof_check` fixture

```python
gpu_proof_check(
    name="my_op",              # unique name within the test
    reference=python_fn,       # callable: the ground truth
    candidate=cuda_fn,         # callable: the GPU implementation
    args=(arg1, arg2),         # positional arguments (tuple)
    kwargs={"key": "val"},     # keyword arguments (dict, optional)
    compare=my_compare_fn,     # optional: (ref_out, cand_out) -> None, raises on mismatch
    metadata={"info": "..."},  # optional: included verbatim in the receipt
)
```

**Default comparison:** `numpy.allclose` for float arrays/tensors, `==` otherwise.

**Custom comparison:** any callable that raises `AssertionError` on mismatch and returns `None` on success.

---

## Markers

| Marker | Effect |
|---|---|
| `@pytest.mark.gpu_proof` | Include test outcomes in the receipt |
| `@pytest.mark.gpu_equivalence` | Alias for `gpu_proof` |
| `@pytest.mark.gpu_required` | Skip test if no GPU is detected (via `nvidia-smi` or `torch.cuda`) |

---

## CLI options

| Option | Default | Description |
|---|---|---|
| `--gpu-proof-enable` | off | Enable receipt generation |
| `--gpu-proof-mode` | `local` | `local` or `ci-gpu` |
| `--gpu-proof-out` | `gpu-proof.json` | Receipt output path |
| `--gpu-proof-key` | auto | SSH private key path |
| `--gpu-proof-signing-backend` | `ed25519` | `ed25519` or `none` (writes an **unsigned** receipt with `"signature": null`; the verifier rejects it unless `--allow-unsigned` is passed) |
| `--gpu-proof-required-marker` | `gpu_proof` | Marker name that flags a test for the receipt |
| `--gpu-proof-fingerprint-paths` | `src,tests` | Comma-separated paths to fingerprint |
| `--gpu-proof-github-user` | auto | GitHub username (auto-detected from git remote) |
| `--gpu-proof-policy` | — | Path to policy YAML |
| `--gpu-proof-fail-on-skip` | off | Exit non-zero and write no receipt if any marked or `gpu_required` test is skipped |

Defaults for most of these can also be set in your project's `pyproject.toml`
under `[tool.gpu_proof]` (CLI flags take precedence):

```toml
[tool.gpu_proof]
mode = "local"
output = "gpu-proof.json"
fingerprint_paths = ["src", "tests"]
required_marker = "gpu_proof"
max_age_days = 30       # used by the verifier
require_gpu = false     # used by the verifier (see below)
```

---

## Verification CLI

```bash
gpu-proof verify \
  --receipt gpu-proof.json \
  --repo . \
  --max-age-days 30

# With an explicit GitHub username (non-GitHub remotes):
gpu-proof verify --receipt gpu-proof.json --github-user myusername
```

Also callable as:

```bash
python -m pytest_gpu_proof verify --receipt gpu-proof.json
```

### What the verifier checks

1. **Signature** — fetches `github.com/{signer}.keys`, verifies Ed25519/ECDSA/RSA signature
2. **Fingerprint** — recomputes SHA-256 digest of `src/` and `tests/`, compares to receipt
3. **Commit SHA** — compares receipt commit SHA to current HEAD
4. **Test outcomes** — all tests recorded in the receipt must have passed; skipped marked tests fail verification unless `--allow-skipped` is passed
5. **Freshness** — receipt must be younger than `max_age_days` (default: 30)
6. **Dirty policy** — configurable via policy file
7. **GPU info** (optional) — with `--require-gpu` (or `require_gpu = true` in `[tool.gpu_proof]`), the receipt's `environment.gpu_info` must be present

Additional flags:

- `--allow-unsigned` — accept receipts with `"signature": null` (produced by `--gpu-proof-signing-backend=none`). This disables the entire trust story; the verifier prints a loud warning.
- `--allow-skipped` — accept receipts that contain skipped marked tests.
- `--require-gpu` — reject receipts whose `environment.gpu_info` is null/absent. This is **modest hardening, not proof**: `gpu_info` is self-reported by the recording machine, so it only guards against accidentally signing on a GPU-less box, not against a dishonest signer.

---

## Key management

**Local mode:** Uses your existing `~/.ssh/id_ed25519` (or whatever `git config user.signingKey` points to). No new keys to generate.

**CI-GPU mode:** Generate a dedicated CI signing key, store the private key as a GitHub Actions secret, and add the public key to your GitHub account.

```bash
ssh-keygen -t ed25519 -f ci-signing-key -N ""
# Add ci-signing-key.pub to github.com/settings/keys
# Add contents of ci-signing-key to GitHub Actions secrets as GPU_PROOF_SIGNING_KEY
```

---

## Receipt format

```json
{
  "schema_version": "1",
  "mode": "local",
  "repo": {
    "remote_url": "git@github.com:you/myrepo.git",
    "github_username": "you",
    "commit_sha": "abc123...",
    "branch": "main",
    "dirty": false
  },
  "fingerprint": {
    "algorithm": "sha256",
    "included_paths": ["src", "tests"],
    "file_count": 12,
    "digest": "deadbeef..."
  },
  "session": {
    "started_at": "2024-01-01T10:00:00Z",
    "ended_at": "2024-01-01T10:01:30Z",
    "node_ids": ["tests/test_relu.py::test_relu"]
  },
  "tests": [
    {
      "node_id": "tests/test_relu.py::test_relu",
      "outcome": "passed",
      "duration_s": 1.23,
      "checks": [{"name": "relu", "outcome": "passed", "metadata": {}}]
    }
  ],
  "environment": {
    "python_version": "3.11.0",
    "platform": "linux",
    "pytest_version": "7.4.0",
    "gpu_info": {"name": "NVIDIA RTX 3090", "driver_version": "535.104"}
  },
  "signature": {
    "algorithm": "ed25519",
    "backend": "ssh-local",
    "signer": "you",
    "key_fingerprint": "SHA256:...",
    "value": "<base64-encoded signature>"
  }
}
```

---

## Security model

A signed receipt proves that **an accepted signer attested to a specific test run over a specific code state**. It does not prove:

- The local machine was fully trustworthy or uncompromised.
- The GPU execution environment was hardware-attested.
- The signing key was protected with a hardware security module.

This is appropriate for **team workflows where the signer is a trusted team member** and the goal is to avoid paying for GPU CI on every merge, not to provide adversarial security guarantees.

The optional `--require-gpu` verifier flag adds a modest extra check — the receipt must contain self-reported `environment.gpu_info` — but this is hardening against mistakes (signing on a GPU-less machine), not proof of GPU execution.

**SSH key support caveats:**

- The plugin signs the raw receipt bytes with the key loaded from disk — it does **not** produce SSHSIG-format signatures, so `ssh-keygen -Y verify` cannot validate receipts. Use `gpu-proof verify` instead.
- Keys that live only in an SSH agent, and FIDO/hardware-backed `sk-ssh-ed25519`/`sk-ecdsa` keys, are **not** supported: signing needs direct access to a private key file readable by the `cryptography` library.

See [docs/security_model.md](docs/security_model.md) for a full discussion.

---

## Examples

| Example | Location | What it shows |
|---|---|---|
| Minimal (no GPU needed) | `examples/minimal_python_only/` | Full plugin flow with pure-Python "fake GPU" |
| Wrapped CUDA via ctypes (fake library) | `examples/wrapped_cuda_ctypes/` | ctypes-style wrapper pattern that runs without CUDA |
| Real CUDA via ctypes | `examples/cuda_ctypes_matmul/` | C ABI CUDA shared library loaded with Python `ctypes` |
| Real CUDA via pybind11 | `examples/cuda_pybind11_matmul/` | CUDA-backed Python extension using `pybind11_add_module` |
| Real CUDA via nanobind | `examples/cuda_nanobind_matmul/` | CUDA-backed Python extension using `nanobind_add_module` |
| Real CUDA via JAX FFI | `examples/jax_ffi_cuda_matmul/` | Typed CUDA custom call registered with `jax.ffi` |
| Local sign, CI verify | `examples/local_receipt_verify/` | GitHub Actions workflow for CPU-only verification |
| CI-GPU execution | `examples/github_gpu_runner/` | GitHub Actions workflow on a GPU runner |

---

## Development

```bash
python3 -m pip install -e ".[dev]"
pytest tests/ -v
```

If you do not want to install the package, run tests directly from the source
tree with:

```bash
PYTHONPATH=src pytest -q
```

Tests are CPU-only. No GPU or network access required.

---

## Compatibility

- Python 3.11+
- pytest 7.0+
- `cryptography` 41.0+
- `pytest-xdist` is **not** supported in v1 (parallel workers would write conflicting receipts)
