# CI-GPU mode

CI-GPU mode uses the same receipt and verifier but records `mode: ci-gpu`.
Choose it when GPU tests must run on a controlled runner rather than a
developer machine.

## Dedicated signing identity

Create a dedicated key and register its public half on the GitHub account named
in the receipt:

```bash
ssh-keygen -t ed25519 -f ci-signing-key -N ""
```

Store the private key as a protected CI secret. A simplified job is:

```yaml
jobs:
  gpu-proof:
    runs-on: YOUR_GPU_RUNNER
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pytest-gpu-proof
      - name: Record GPU receipt
        env:
          GPU_PROOF_KEY: ${{ secrets.GPU_PROOF_SIGNING_KEY }}
        run: |
          install -m 600 /dev/null /tmp/gpu-proof-key
          printf '%s' "$GPU_PROOF_KEY" > /tmp/gpu-proof-key
          pytest tests/gpu --gpu-proof-enable \
            --gpu-proof-mode=ci-gpu \
            --gpu-proof-key=/tmp/gpu-proof-key \
            --gpu-proof-github-user=gpu-ci \
            --gpu-proof-out=gpu-proof.json
      - uses: actions/upload-artifact@v4
        with:
          name: gpu-proof-receipt
          path: gpu-proof.json
```

Use your platform's secret-file mechanism where available, and delete the
temporary key in an `always()` cleanup step.

## Enforce the origin mode and signer

```yaml
signer_mode: restricted
allowed_signers: [gpu-ci]
allowed_key_fingerprints: ["SHA256:..."]
require_mode: ci-gpu
max_age_days: 7
allow_dirty: false
```

The mode field is signed, so it cannot be changed from `local` after the run.
It still does not itself prove that GitHub or a particular runner executed the
tests; the controlled workflow and key custody provide that operational trust.
