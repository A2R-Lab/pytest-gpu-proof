# Verification policy

Policy is a repository-owned JSON or YAML object passed to `gpu-proof verify`.
Unknown fields are errors, preventing a misspelled control from silently doing
nothing.

## Open contributor mode

Open mode is the default. Any GitHub user whose current public SSH key verifies
the signed identity may submit a receipt:

```yaml
signer_mode: open
max_age_days: 30
require_mode: local
required_fingerprint_paths: ["."]
required_fingerprint_excluded_paths: [gpu-proof.json]
allow_dirty: false
allow_carried: false
```

This works well for pull requests: the author signs with their own key and the
reviewer sees exactly who attested to the run.

## Restricted mode

Restricted mode requires at least one allowlist:

```yaml
signer_mode: restricted
allowed_signers: [alice, gpu-ci]
allowed_key_fingerprints:
  - "SHA256:base64-fingerprint"
```

If both lists are present, the username and key must both be allowed. Key
fingerprints are useful for dedicated CI keys or explicit key rotation.

## Full field reference

| Field | Meaning |
|---|---|
| `signer_mode` | `open` or `restricted` |
| `allowed_signers` | GitHub usernames accepted in restricted mode |
| `allowed_key_fingerprints` | SSH SHA-256 fingerprints accepted in restricted mode |
| `max_age_days` | Maximum age of the merged/session receipt |
| `require_mode` | Required receipt mode: `local` or `ci-gpu` |
| `allow_dirty` | Permit dirty recording or verification trees |
| `required_fingerprint_paths` | Exact tracked path list |
| `required_fingerprint_extra_paths` | Exact generated/ignored path list |
| `required_fingerprint_excluded_paths` | Exact receipt/self-reference exclusion list |
| `required_test_manifest` | Repository-relative file containing exact node IDs |
| `required_shard_fingerprints` | Exact paths/extras for every named shard |
| `allow_carried` | Permit carry-forward shards |
| `carried_max_age_days` | Maximum age of each carried shard's original run |

Example shard scope:

```yaml
required_shard_fingerprints:
  l1:
    paths: [src/l1, tests/gpu/test_l1.py]
    extra_paths: [generated/l1_table.cuh]
    excluded_paths: [gpu-proof.json]
  solvers:
    paths: [src/solvers, tests/gpu/test_solvers.py]
    extra_paths: []
    excluded_paths: [gpu-proof.json]
```

The required shard names must exactly match the receipt. Within each scope,
only listed fields are pinned; list `paths`, `extra_paths`, and
`excluded_paths` when policy should lock the complete scope.

## CLI-only controls

`--allow-unsigned`, `--allow-skipped`, `--expected-skips`, and `--require-gpu`
are verifier flags. `max_age_days`, `require_gpu`, and inline
`expected_skips` can also be read from `[tool.gpu_proof]`.

Unsigned acceptance authenticates no signer. Treat it as a development tool,
not a repository trust policy.
