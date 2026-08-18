# pytest-gpu-proof

**Signed pytest receipts for local GPU runs, verified in CPU-only CI.**

The plugin turns an ordinary marked pytest run into a signed, reviewable
artifact. The receipt binds a signer, exact test node IDs and outcomes, a Git
commit, a source manifest, timestamps, and environment metadata. CPU-only CI
validates those claims without importing CUDA or rerunning the GPU suite.

```text
local or lab GPU                         ordinary CI runner
─────────────────────────────────        ─────────────────────────────
pytest --gpu-proof-enable       ───────▶ gpu-proof verify
run + fingerprint + sign                 authenticate + recompute + policy
```

The default open signer mode supports contributor-signed pull requests.
Restricted policy can instead allowlist maintainers, dedicated CI accounts,
or exact SSH key fingerprints.

!!! important
    A receipt proves that a GitHub-key holder attested to the signed payload.
    It does not prove that the GPU or local machine was trustworthy. Read the
    [security model](security_model.md).

## Start here

- [Quickstart](quickstart.md): add a test, record a receipt, verify it in CI.
- [Local mode](local_mode.md): signer discovery, source scope, and failures.
- [Policy](policy.md): open and restricted trust policies.
- [Sharding and merge](sharding.md): separate processes and carry-forward.
- [CI-GPU mode](ci_gpu_mode.md): produce receipts in controlled GPU CI.
- [Architecture](architecture.md): schema and data flow.
- [Security model](security_model.md): exact guarantees and limits.

Requirements: Python 3.11+, pytest 7+, and an SSH private-key file whose public
key is registered on GitHub.
