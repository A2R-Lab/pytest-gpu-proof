# Architecture

## Package layout

```
src/pytest_gpu_proof/
  __init__.py          version
  plugin.py            pytest hooks, CLI option registration, gpu_proof_check fixture
  config.py            GpuProofConfig dataclass, load_config()
  gitutils.py          git helpers: commit SHA, branch, dirty state, remote URL, GitHub username
  fingerprint.py       deterministic SHA-256 fingerprint of source files
  compare.py           run_comparison(), default_compare() (numpy.allclose / ==)
  receipt.py           build_receipt_payload(), finalize_receipt(), write_receipt()
  verify.py            _verify() with all checks, verify_receipt() public API
  cli.py               argparse entry point for `gpu-proof verify`
  __main__.py          enables `python -m pytest_gpu_proof verify`
  signers/
    base.py            SignerBase ABC, VerifierError
    ed25519.py         SSHSigner, fetch_github_public_keys(), verify_with_github_keys()
```

## Data flow

### Local mode (signing)

```
pytest session start
  │
  ├── plugin.pytest_sessionstart()        record started_at
  │
  ├── [tests run]
  │     gpu_proof_check fixture           run_comparison(reference, candidate)
  │     pytest_runtest_makereport hook    collect outcome + checks per test
  │
  └── plugin.pytest_sessionfinish()
        build_receipt_payload()           git state + fingerprint + test results + env
        SSHSigner.sign(canonical_json)    Ed25519 via ~/.ssh/id_ed25519
        finalize_receipt()                embed signature block
        write_receipt()                   → gpu-proof.json
```

### Verification

```
gpu-proof verify --receipt gpu-proof.json
  │
  ├── load receipt JSON
  ├── extract signature block, compute canonical payload
  ├── fetch github.com/{signer}.keys
  ├── verify signature against each key
  ├── recompute fingerprint, compare digest
  ├── compare commit SHA to current HEAD
  ├── check all test outcomes == "passed"
  ├── check receipt age ≤ max_age_days
  └── exit 0 (pass) or 1 (fail)
```

## Receipt signing

The signature covers the **canonical JSON** of the receipt without the `signature` field:

```python
payload = {k: v for k, v in receipt.items() if k != "signature"}
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
signature = private_key.sign(canonical)
```

This means the human-readable indented `gpu-proof.json` on disk is verifiable:
the verifier simply strips the `signature` key and re-canonicalizes before verifying.

## Key discovery order (signing)

1. `--gpu-proof-key=PATH` CLI option
2. `git config user.signingKey` (expanded with `~`)
3. `~/.ssh/id_ed25519`
4. `~/.ssh/id_ecdsa`
5. `~/.ssh/id_rsa`

If none found, signing is skipped with a warning (tests still pass; just no receipt).

## GitHub username discovery order

1. `--gpu-proof-github-user=USERNAME` CLI option
2. `config.github_username` (from pyproject.toml `[tool.gpu_proof]`)
3. Parsed from `git remote get-url origin`:
   - `git@github.com:username/repo.git` → `username`
   - `https://github.com/username/repo.git` → `username`

## Key type support

The signing layer handles Ed25519, ECDSA (P-256/P-384), and RSA-PSS keys transparently.
Ed25519 is recommended for new keys — it is the fastest and produces 64-byte signatures.
