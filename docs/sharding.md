# Sharding and merge

Large GPU suites often need crash isolation or shorter retry units. Run each
shard as a separate pytest process. Receipt emission deliberately rejects
xdist workers because concurrent hooks cannot safely own one artifact.

## Record explicit shards

```bash
pytest tests/gpu/l1 --gpu-proof-enable \
  --gpu-proof-shard=l1 \
  --gpu-proof-shard-fingerprint-paths=src/l1,tests/gpu/l1 \
  --gpu-proof-shard-fingerprint-extra-paths=generated/l1.cuh \
  --gpu-proof-out=receipts/l1.json
```

Each input is independently readable as a complete schema-3 receipt. The
shard block adds a unique name, narrow manifest, exact member node IDs,
environment, timestamps, and optional carry metadata.

## Merge

```bash
gpu-proof merge receipts/l1.json receipts/solvers.json \
  --out gpu-proof.json \
  --github-user YOUR_USER
```

Merge refuses inputs that disagree on:

- schema, commit, global fingerprint, or mode;
- Python, platform, pytest, or plugin version;
- duplicate test node IDs or duplicate shard names.

Dirty state is ORed. GPU information comes from the first input that has it.
Session times span the inputs and schema-3 session outcome fails if any input
session failed.

The merged receipt records input source names, counts, times, and recorded
signers, then signs the result with the merger's key. Input signatures are
provenance, not independently verified during offline merge. The merger
attests to the union.

## Carry forward unchanged shards

```bash
gpu-proof merge receipts/fresh-l1.json \
  --carry-from last-green/gpu-proof.json \
  --repo . \
  --out gpu-proof.json
```

An absent old shard is carried only when:

1. its receipt commit is the current commit or an ancestor;
2. its stored narrow manifest—including explicit extra paths—recomputes
   identically at the current tree;
3. it does not duplicate a fresh node ID;
4. every claimed node ID exists in the old tests list.

Freshly rerun shards always win. Changed or malformed scopes require a rerun.

Verification rejects carried shards by default:

```yaml
allow_carried: true
carried_max_age_days: 14
required_shard_fingerprints:
  l1:
    paths: [src/l1, tests/gpu/l1]
    extra_paths: [generated/l1.cuh]
    excluded_paths: [gpu-proof.json]
```

The required shard map pins both the full shard set and every declared scope.
Carry-forward remains weaker than a fresh run; use it only when the dependency
boundaries are reviewable and complete.
