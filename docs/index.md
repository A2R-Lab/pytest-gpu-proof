# pytest-gpu-proof

A pytest plugin that lets you run GPU equivalence tests locally, sign the results with your existing SSH key, and have GitHub Actions verify the receipt — **without re-running the GPU tests in CI**.

The trust model is simple: if you can push to GitHub, you can sign a receipt. Verification fetches your public keys from `github.com/{username}.keys`, exactly as SSH does.

> **Requirements:** Python 3.11+ · pytest 7.0+ · cryptography 41.0+
> The package is not yet on PyPI — install from source with `pip install -e .` or `pip install "git+https://github.com/A2R-Lab/pytest-gpu-proof.git"`.

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

## Documentation

- [Quickstart](quickstart.md) — local CUDA proof, GitHub verification, end to end
- [Local Mode](local_mode.md) — the default workflow: sign locally, verify in CI
- [CI-GPU Mode](ci_gpu_mode.md) — run the tests on a GitHub-hosted GPU runner instead
- [Architecture](architecture.md) — package layout and data flow
- [Security Model](security_model.md) — what a receipt does and does not prove
- [Landscape](landscape.md) — why this tool exists rather than an existing one

See the [README on GitHub](https://github.com/A2R-Lab/pytest-gpu-proof#readme) for the full CLI reference, receipt format, and examples.
