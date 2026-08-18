# Local mode

Local mode is the primary workflow: run tests on a developer or lab GPU, sign
the result, and let CPU-only CI verify it.

## Recording contract

With `--gpu-proof-enable`, receipt generation is fail-closed:

- no selected tests is an error;
- setup, call, and teardown failures are recorded;
- an interrupted test without a terminal report becomes an error;
- missing Git metadata, empty fingerprints, missing keys, and write failures
  fail pytest;
- the previous output is removed at session start, so a failed run cannot
  leave a stale success artifact.

`--gpu-proof-best-effort` converts receipt-generation errors to warnings. It is
useful while integrating the plugin, but it should not be used in a release or
merge workflow.

## Signer and key discovery

The GitHub username is selected from:

1. `--gpu-proof-github-user` or `[tool.gpu_proof].github_username`;
2. authenticated `gh api user` output;
3. the origin owner, with a warning.

Set the username explicitly for organization-owned repositories. The receipt
must name the account that actually owns the public SSH key.

The private-key file is selected from:

1. `--gpu-proof-key`;
2. `git config user.signingKey`;
3. `~/.ssh/id_ed25519`, `id_ecdsa`, or `id_rsa`.

Encrypted key files prompt for a passphrase. SSH-agent-only and hardware-backed
keys are not currently supported.

## Source fingerprint

The safe default is the entire tracked repository:

```toml
[tool.gpu_proof]
fingerprint_paths = ["."]
```

The manifest binds tracked file bytes, symlink targets, executable modes, and
submodule gitlinks. Untracked build debris is excluded. Explicitly add ignored
or generated dependencies:

```toml
fingerprint_extra_paths = [
  "generated/kernel_table.cuh",
  "vendor/generated-config.json",
]
fingerprint_excluded_paths = ["gpu-proof.json"]
```

The default receipt exclusion prevents a tracked `gpu-proof.json` from
hashing its previous contents and invalidating its replacement. Change this
list when the committed final receipt uses another path. Exclusions weaken the
scope like any omission, so repository policy should pin them.

Narrowing the tracked paths narrows the claim. Only do it when repository
policy independently pins the scope and the omitted files cannot influence
the run.

## Clean trees and commit ancestry

Schema-3 verification rejects a dirty recording tree or dirty verification
tree by default. The receipt commit may equal the verified commit or be its
ancestor; the manifest must still match the checked-out tree. A policy may set
`allow_dirty: true`, but this weakens reproducibility.

## Skips

Selected skips are recorded and rejected by default.

- `--gpu-proof-fail-on-skip` fails recording and writes no receipt.
- `--expected-skips FILE` accepts exactly the listed node IDs at verification.
- `--allow-skipped` accepts any selected skip and is intentionally broad.

An exact baseline catches both new skips and stale entries that now run.
