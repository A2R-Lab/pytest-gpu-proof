# CI-GPU Mode

CI-GPU mode runs the same tests on a GitHub-hosted GPU runner and emits the same
signed receipt. Use this when you need the receipt to come from a controlled
environment rather than a developer laptop.

## When to use CI-GPU mode

- Compliance requirements specify where GPU tests must run.
- You cannot trust individual developer machines for signing.
- You want the receipt to be tied to a CI identity, not a personal SSH key.
- You want to validate that the code works on a fresh, clean environment.

## Prerequisites

- A GitHub plan that includes GPU-powered larger runners.
  See [GitHub-hosted runners documentation](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners).
- A dedicated CI signing key.

## Setting up a CI signing key

```bash
# Generate a dedicated Ed25519 key for CI signing
ssh-keygen -t ed25519 -f ci-signing-key -N ""

# Add the PUBLIC key to your GitHub account
# → github.com/settings/keys → "New SSH key"
cat ci-signing-key.pub

# Add the PRIVATE key as a GitHub Actions secret
# → Repository → Settings → Secrets and variables → Actions → "New repository secret"
# Name: GPU_PROOF_SIGNING_KEY
cat ci-signing-key
```

The verifier will fetch the public key from `github.com/{your-username}.keys` automatically.

## Example GitHub Actions workflow

```yaml
name: GPU Tests (CI-GPU mode)

on:
  schedule:
    - cron: "0 3 * * 1"   # weekly — GPU runners cost money
  workflow_dispatch:

jobs:
  gpu-test:
    runs-on: ubuntu-latest-gpu-4   # your plan's GPU runner label

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install pytest-gpu-proof

      - name: Run GPU tests
        env:
          GPU_PROOF_KEY_DATA: ${{ secrets.GPU_PROOF_SIGNING_KEY }}
        run: |
          echo "$GPU_PROOF_KEY_DATA" > /tmp/ci-key
          chmod 600 /tmp/ci-key
          pytest tests/ \
            --gpu-proof-enable \
            --gpu-proof-mode=ci-gpu \
            --gpu-proof-key=/tmp/ci-key \
            --gpu-proof-out=gpu-proof.json \
            -v
          rm -f /tmp/ci-key

      - name: Upload receipt
        uses: actions/upload-artifact@v4
        with:
          name: gpu-proof-receipt
          path: gpu-proof.json
          retention-days: 90
```

## Key difference from local mode

In local mode, the receipt is signed with the developer's personal SSH key.
In CI-GPU mode, it is signed with a dedicated CI key — but the verification
mechanism is identical: the verifier fetches `github.com/{username}.keys`.

The receipt `mode` field will contain `"ci-gpu"` instead of `"local"`, which
policy files can use to enforce that only CI-produced receipts are accepted.

## Policy enforcement example

```yaml
# gpu-proof-policy.yaml
allow_dirty: false
max_age_days: 7
```

With `require_mode: ci-gpu` planned for a future version.
