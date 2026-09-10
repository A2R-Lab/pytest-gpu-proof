# Landscape Memo

## Purpose

This memo documents why `pytest-gpu-proof` was built rather than adopting an existing tool.

## Search terms used

- `pytest gpu test plugin`
- `pytest signed receipt attestation`
- `pytest artifact signing`
- `pytest equivalence testing`
- `GPU test attestation python`
- `pytest-json-report`, `pytest-artifacts` (direct name searches)
- `sigstore python signing pytest`
- `NVIDIA attestation SDK python`
- PyPI full-text search: `gpu proof`, `gpu attestation`, `gpu equivalence`

## Existing tools evaluated

### pytest-json-report

**What it does:** Emits a JSON report of the test session (outcomes, durations, log output).

**Gap:** No signing, no code fingerprinting, no GPU-specific helpers.
Useful as a complement to this plugin but does not replace it.

### pytest-artifacts

**What it does:** Collects and uploads test artifacts (logs, screenshots) to a configurable store.

**Gap:** No signing, no equivalence checking, no GPU concept.

### GitHub artifact attestations + Sigstore

**What it does:** Signs GitHub Actions workflow artifacts with Sigstore keyless signing,
tied to the GitHub Actions OIDC identity and logged in the Rekor transparency log.

**Gap:** Works only inside GitHub Actions. Cannot sign a receipt produced on a local developer
machine or lab GPU. Has no pytest integration layer, no equivalence testing helpers,
and no verifier that understands pytest test outcomes.

### Sigstore Python client (`sigstore` PyPI package)

**What it does:** Programmatic access to Sigstore signing and verification in Python.

**Gap:** A library, not a pytest plugin. No GPU equivalence concept, no receipt format,
no pytest hooks. Suitable as a future optional signing backend for this plugin.

### NVIDIA Attestation SDK (`nv-attestation-sdk`)

**What it does:** Hardware-level attestation for NVIDIA Hopper GPUs running in
Confidential Computing environments. Produces cryptographic evidence that specific
code ran on specific verified GPU hardware.

**Gap:** Requires Hopper-generation hardware and a Confidential Computing environment.
Far too heavyweight for ordinary GPU correctness testing. Solves a different problem
(hardware trust) than this plugin (team workflow trust).

### pytest-randomly, pytest-benchmark, pytest-cov

None of these are relevant. Included for completeness; all solve adjacent problems.

## Conclusion

No maintained package combines:

- GPU equivalence test helpers (reference vs. candidate comparison)
- Signed receipt / attestation output
- Local-first verification flow (SSH key, no cloud dependency)
- Optional CI-GPU execution mode
- GitHub-friendly verification policy (public key from `github.com/{user}.keys`)

Building `pytest-gpu-proof` as a focused, narrow package is justified.
The implementation reuses `cryptography` (Ed25519, SSH key parsing) and standard
pytest hooks rather than inventing new infrastructure.
