# Security Model

## What a signed receipt proves

A receipt signed with `pytest-gpu-proof` proves that:

1. **A specific signer** (identified by their GitHub SSH key) ...
2. **attested to a specific test run** (named test node IDs, all of which passed) ...
3. **over a specific code state** (SHA-256 fingerprint of `src/` and `tests/`) ...
4. **at a specific time** (UTC timestamps in the session block) ...
5. **at a specific git commit** (commit SHA recorded in the receipt).

## What it does NOT prove

| Claim | Status |
|---|---|
| The local machine was uncompromised | ❌ Not proven |
| The GPU hardware ran the code faithfully | ❌ Not proven (no hardware attestation) |
| The signing key was stored in a hardware security module | ❌ Not proven |
| The tests were run exactly once and not cherry-picked | ❌ Not enforced by the receipt alone |
| The signer is who they claim to be (beyond their GitHub identity) | ❌ Depends on GitHub account security |

## Why a plain hash is not enough

A SHA-256 hash of the code can be recomputed by anyone without running the tests.
A signed receipt requires the private key, which only the signer holds — so the receipt
proves the signer's involvement, not just the existence of a code state.

## Why local signing is still useful

For team workflows, the practical threat is **accidental breakage**, not adversarial attack.
The receipt answers the question "did someone with write access to this repository actually
run these GPU tests against this exact code and confirm they passed?" That is sufficient for:

- Avoiding GPU cloud spend on every CI run
- Auditing which commits have been GPU-validated and by whom
- Catching the common failure mode of "tests passed last time I ran them manually"

## When to prefer GitHub GPU execution instead

Use `--gpu-proof-mode=ci-gpu` (GitHub GPU runner) when:

- Your team cannot trust individual developer machines.
- You need proof that runs happened in a controlled environment.
- Your compliance requirements specify where tests must run.
- You want the receipt produced by a key that is not on a developer laptop.

## Trust hierarchy

```
Strongest                    Weakest
   │
   ├── Hardware attestation (NVIDIA HOPPER TEE, Confidential Computing)
   │     Proves GPU HW faithfully executed the code
   │
   ├── GitHub Actions GPU runner + Sigstore keyless
   │     Proves GitHub's infrastructure ran the code
   │     Signer identity tied to GitHub OIDC, logged in Rekor transparency log
   │
   ├── GitHub Actions GPU runner + SSH key (CI-GPU mode)
   │     Proves a CI job ran the code
   │     Key is a GitHub Actions secret, not on any developer laptop
   │
   └── Local SSH key (local mode — this plugin's default)
         Proves a developer with GitHub push access ran the code
         Key security depends on the developer's machine
```

## Future extension: hardware attestation

NVIDIA's Attestation SDK (Hopper and later) can produce hardware-level evidence
that a specific GPU executed a specific workload in a verified environment.
This is out of scope for v1 but the receipt format is designed to be extendable —
a `hardware_attestation` block could be added to the `environment` section in a
future version without breaking existing receipts.
