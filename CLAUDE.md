# Claude orientation

Use [AGENTS.md](AGENTS.md) as the canonical agent guide. In particular:

- a receipt is signer attestation, not proof of GPU execution;
- receipt, fingerprint, signature, Git, merge, and policy code fail closed;
- new recordings use schema 3 and bind signer metadata inside the signature;
- the default manifest covers the full tracked repository;
- tests are hermetic and maintain 100% line and branch coverage;
- generated `site/`, `dist/`, coverage output, real keys, and local receipts are
  not source changes.

Before implementation work, read `docs/architecture.md`,
`docs/security_model.md`, `docs/policy.md`, and `CONTRIBUTING.md`.
