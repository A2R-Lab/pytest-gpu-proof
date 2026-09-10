# Security model

## What verification establishes

A valid schema-3 receipt establishes that a private-key holder corresponding
to a current SSH public key on the named GitHub account signed a payload that:

- names an exact selected pytest collection;
- records terminal session, test, and comparison outcomes;
- binds a Git commit and deterministic source manifest;
- records UTC run times and software/environment metadata;
- satisfies the repository's verification policy at verification time.

In plain language: **the signer attests that these tests passed over this code
state at this time**.

## What it does not establish

| Claim | Established? |
|---|---|
| The signing machine was uncompromised | No |
| A physical GPU executed every operation | No |
| Self-reported GPU metadata is honest | No |
| The tests are sufficient or scientifically valid | No |
| The signer ran the tests exactly once | No |
| GitHub account/key control maps to a legal identity | No |
| A merged input shard's original signature was verified by the merger | No |

This is not remote execution proof, a trusted execution environment, or
hardware attestation. `--require-gpu` catches accidental GPU-less recording;
it does not resist a dishonest signer.

## Why it is useful

Many GPU projects otherwise rely on an unaudited statement that someone ran
tests locally. The receipt makes that workflow explicit and machine-checkable:

- code drift invalidates the manifest;
- stale receipts fail freshness policy;
- incomplete collections and setup/teardown failures are visible;
- signer identity and key fingerprint are signed;
- contributor receipts can be reviewed in open mode;
- sensitive repositories can restrict users or keys.

The practical target is accidental breakage and accountable review, not a
malicious developer who controls both the test environment and signing key.

## Signer policy

Open mode accepts any valid GitHub-key holder. It does not imply repository
write access; GitHub branch protection and PR review remain responsible for
authorization. This is intentional so external contributors can submit
receipts signed by themselves.

Restricted mode adds repository-owned username and/or key-fingerprint
allowlists. If both are configured, both must match.

GitHub key lookup uses the account's **current** `.keys` endpoint. Key removal
therefore invalidates future verification of old receipts unless another
registered key happens to match. This is useful revocation behavior, but the
project does not provide archival key transparency.

## Source and test scope

The default source scope is the whole tracked repository. Narrower global or
shard scopes weaken the claim because omitted files may influence builds or
tests. Policy can require exact path lists and an exact test node-ID manifest.

Ignored and generated inputs are not included automatically; projects must
declare them through `fingerprint_extra_paths`. Missing, empty, unreadable,
escaping, or unmerged inputs fail closed.

## Dirty trees and replay

Schema 3 rejects dirty recording and verification trees by default. A receipt
may verify at its exact commit or a descendant only when the source manifest
still matches. Freshness limits replay duration but no server-issued nonce is
currently used.

`allow_dirty: true`, long age limits, `--allow-skipped`, and
`--allow-unsigned` weaken guarantees. Unsigned mode authenticates no signer,
and a `signer_mode: restricted` policy therefore refuses unsigned receipts
regardless of `--allow-unsigned`. The receipt file under verification is
itself excluded from the verification-tree dirty check (its integrity is
protected by its signature, not by Git state), so the canonical
run-then-verify flow works without gitignoring the receipt.

Legacy schema-1/2 receipts remain verifiable for migration, with weaker
identity binding: the signer username and key fingerprint are not part of the
signed payload. The verifier compensates by deriving the policy-checked
fingerprint from the key that actually verified the signature; pin
`min_schema: 3` to refuse legacy receipts entirely once migration is done.

## Merge and carry-forward

The merger records shard signer provenance but does not fetch keys or verify
each input signature. The merger's signature attests to the union. A review
workflow that needs independent shard authentication should verify every
input before merging.

Carry-forward means a test passed at an ancestor commit and its declared shard
inputs are byte-identical now. It does not establish that omitted dependencies
or the old environment remain equivalent. Carried shards are rejected unless
policy opts in and bounds their original age.

## Stronger alternatives

Use controlled GPU CI when the local machine cannot be trusted. Hardware
attestation, confidential computing, Sigstore/OIDC provenance, and transparent
execution logs can establish stronger properties, but are outside this
plugin's current scope.
