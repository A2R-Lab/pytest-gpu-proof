# Architecture

## Components

```text
pytest hooks + fixture
        │
        ▼
receipt payload ── source manifest ── Git metadata ── environment
        │
        ▼
canonical JSON + SSH signature
        │
        ▼
schema-3 receipt
        │
        ├── verify: schema → signature → tree → outcomes → policy
        └── merge: compatible shards → union → merger signature
```

| Module | Responsibility |
|---|---|
| `plugin.py` | pytest options, collection, phase outcomes, fixture checks |
| `config.py` | CLI/TOML precedence and runtime configuration |
| `gitutils.py` | strict Git queries and tracked-index entries |
| `fingerprint.py` | deterministic tracked/extra manifest |
| `compare.py` | reference/candidate execution and comparison |
| `receipt.py` | payload construction, canonicalization, atomic output |
| `signers/ed25519.py` | Ed25519/ECDSA/RSA signing and GitHub key lookup |
| `verify.py` | schema, signature, repository, test, shard, and policy checks |
| `merge.py` | compatible shard union and controlled carry-forward |

## Recording sequence

1. Session start records time and removes the old output.
2. Collection records the exact selected node-ID sequence.
3. `pytest_runtest_makereport` observes setup, call, and teardown.
4. `gpu_proof_check` stores named comparison outcomes on the test item.
5. Session finish fills any missing terminal reports as errors.
6. Receipt construction requires a Git repository and nonempty source scope.
7. Signer metadata is inserted into the payload before canonicalization.
8. The JSON file is flushed, fsynced, and atomically replaced.

Receipt-generation failure changes pytest's exit status unless explicit
best-effort mode was requested.

## Schema 3

The top-level blocks are:

- `repo`: remote, signed GitHub identity, commit, branch, and dirty state;
- `fingerprint`: manifest algorithm, tracked paths, extra paths, count, digest;
- `session`: start/end, pass/fail, exact node IDs, pytest arguments;
- `tests`: terminal outcome, phase, duration, and comparison checks;
- `environment`: Python, platform, pytest, plugin, and self-reported GPU data;
- `shards`: optional narrow manifests and carry metadata;
- `signer`: signed username, algorithm, backend, and key fingerprint;
- `signature`: base64 signature value only.

The signature covers canonical JSON for every field except `signature`:

```python
payload = {key: value for key, value in receipt.items() if key != "signature"}
canonical = json.dumps(
    payload, sort_keys=True, separators=(",", ":"), allow_nan=False
).encode()
```

Putting signer metadata inside this payload prevents identity or algorithm
substitution after signing.

## Fingerprint manifest

`sha256-manifest-v2` enumerates stage-0 Git index entries. Regular files bind
bytes and mode, symbolic links bind their target string, and submodules bind
the checked-out commit or index gitlink. Explicit extra paths add ignored or
generated files without sweeping unrelated build output into the claim. The
committed receipt path is an explicit exclusion because its final signed bytes
cannot recursively be an input to its own digest.

The digest is over canonical JSON for the file map, not a concatenation with
ambiguous boundaries.

## Verification order

The verifier fails at the first invalid trust boundary:

1. repository and JSON readability;
2. supported schema and strict structure;
3. signature and signed identity;
4. repository policy and fingerprint;
5. Git ancestry and dirty-tree policy;
6. shard and carry-forward consistency;
7. session, test, comparison, and skip outcomes;
8. required test manifest and GPU metadata;
9. timestamp validity and freshness.

Legacy schema-1/2 receipts remain readable, but schema 3 uses stricter clean
tree and signed-identity defaults.
