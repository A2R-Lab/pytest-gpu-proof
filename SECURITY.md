# Security policy

## Reporting

Please report vulnerabilities through GitHub's private security advisory flow
for `A2R-Lab/pytest-gpu-proof`. Do not open a public issue for a bypass that
could cause an invalid receipt to verify.

Include:

- affected version or commit;
- receipt/policy sample with secrets removed;
- expected and observed verifier behavior;
- reproduction steps and impact.

## In scope

- signature or signed-identity bypasses;
- source fingerprint omissions or path escapes;
- incomplete test/session outcomes accepted as passing;
- policy fields that fail open;
- stale/carry-forward/ancestry bypasses;
- unsafe private-key handling or receipt writes.

The documented limits in the [security model](docs/security_model.md)—including
the absence of hardware attestation and trust in the local signer—are not
vulnerabilities by themselves.

## Supported versions

Until 1.0, security fixes are made on the latest released minor version. Older
schema receipts may remain verifiable for migration, but new recordings use
the current schema and stricter defaults.
