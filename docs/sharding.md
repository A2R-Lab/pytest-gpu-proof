# Sharded runs & merging receipts

Large suites often can't (or shouldn't) run as one pytest session: per-module
subprocesses give crash isolation (one CUDA abort no longer erases the whole
run's results), and big projects split GPU tests across invocations or
machines. Each invocation emits its own receipt; CI wants **one** artifact.

## Emit one receipt per shard

Point each invocation at its own output path:

```bash
pytest tests/gpu/test_a.py --gpu-proof-enable --gpu-proof-out=receipts/a.json
pytest tests/gpu/test_b.py --gpu-proof-enable --gpu-proof-out=receipts/b.json
```

Every shard receipt is a complete, individually verifiable receipt.

## Merge

```bash
gpu-proof merge --out gpu-proof.json receipts/a.json receipts/b.json
```

`merge` unions the shards' `tests`, spans `session.started_at`/`ended_at`
across them, records per-shard provenance under `session.shards`
(`source`, `node_count`, timestamps, and each shard's recorded signer), and
**re-signs the merged payload with your local SSH key**. The result flows
through `gpu-proof verify` completely unchanged — same schema, same seven
checks.

Options:

- `--github-user USERNAME` — recorded signer identity for the merged receipt
  (default: the first shard's `repo.github_username`).
- `--key PATH` — SSH private key (default: `git config user.signingKey`, then
  `~/.ssh/id_ed25519` / `id_ecdsa` / `id_rsa`).
- `--unsigned` — write `signature: null`; verifies only with
  `--allow-unsigned`, loudly.

## What merge refuses

A merged receipt must mean exactly what a single-session receipt means, so
`merge` hard-refuses shards that disagree on anything a receipt pins:

- `schema_version`, `repo.commit_sha`, `fingerprint` (digest + paths),
  `mode`, or the `environment` the tests ran under (python/pytest/plugin
  versions, platform);
- **duplicate node IDs across shards** — two shards attesting the same test is
  a sharding bug in the runner, never something to dedupe silently.

`repo.dirty` is OR-ed: one dirty shard makes the merged attestation dirty, and
your verify-time dirty policy applies honestly. `gpu_info` is taken from the
first shard that has one, so a CPU-only shard doesn't erase the GPU record.

## Trust model

Consistent with the [security model](security_model.md): the merged receipt is
an **attestation by the merger**. Shard signatures are recorded as provenance
but not re-verified at merge time (merging is offline); the merged signature
is what CI verifies. If shards were signed by someone else, verification of
the merged receipt attests that *you* vouch for the union.

## Per-shard fingerprints & carry-forward (schema 2)

Declare each invocation as a **shard** and the receipt becomes schema `"2"`,
carrying that shard's own *narrow* fingerprint over the paths you declare:

```bash
pytest tests/gpu/test_a.py --gpu-proof-enable \
    --gpu-proof-shard=test_a \
    --gpu-proof-shard-fingerprint-paths=tests/gpu/test_a.py,src/kernels_a \
    --gpu-proof-out=receipts/a.json
```

`gpu-proof merge` unions schema-2 shards exactly like schema-1 receipts (shard
names must be unique). The new capability is **carry-forward**:

```bash
gpu-proof merge --out gpu-proof.json --carry-from last-green/gpu-proof.json \
    --repo . receipts/*.json
```

Shards present in the old receipt but absent from the fresh inputs are grafted
in, **marked `carried`**, iff:

1. the old receipt's commit is an **ancestor** of the fresh one (same history), and
2. the shard's narrow fingerprint **recomputes identical** against the current
   tree — the inputs that shard proved are unchanged.

A shard whose inputs changed refuses to carry (re-run it). Freshly re-run
shards always win over old ones.

### Verification of schema-2 receipts

`gpu-proof verify` additionally checks, for every shard: the narrow
fingerprint recomputes clean at the verifying tree, and shard membership
exactly partitions `tests[]`. **Carried shards are rejected by default** — the
policy must opt in:

```yaml
allow_carried: true          # default false — the trust boundary
carried_max_age_days: 30     # carried shard's ORIGINAL run must be fresher
```

A receipt with carried shards verified under `allow_carried: true` means:
*every test either ran at this commit, or ran at an ancestor commit on inputs
that are provably byte-identical today, within the age window* — and the
merger signed for that claim.
