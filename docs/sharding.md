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
