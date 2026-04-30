# Quickstart

This guide gets you from zero to a verified GPU receipt in five minutes.
No GPU required for the demo — use `examples/minimal_python_only/`.

## Install

```bash
pip install pytest-gpu-proof
```

## Run the demo (no GPU needed)

```bash
cd examples/minimal_python_only
pytest test_minimal.py --gpu-proof-enable -v
```

You should see:

```
PASSED test_minimal.py::test_relu
PASSED test_minimal.py::test_softmax
...
[gpu-proof] Receipt written to gpu-proof.json
[gpu-proof] Signed with key SHA256:...
```

## Verify the receipt

```bash
gpu-proof verify --receipt gpu-proof.json
```

The verifier fetches your public keys from `github.com/{you}.keys` and checks
the signature, fingerprint, commit SHA, test outcomes, and freshness.

## Next steps

- [Local mode walkthrough](local_mode.md) — full workflow for real GPU tests
- [CI-GPU mode](ci_gpu_mode.md) — run tests on a GitHub GPU runner
- [Architecture](architecture.md) — how the plugin works internally
- [Security model](security_model.md) — what the receipt proves and what it does not
