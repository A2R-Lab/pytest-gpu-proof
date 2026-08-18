# Agent guide

This repository is a security-sensitive pytest plugin. Preserve fail-closed
behavior and treat receipt, fingerprint, signature, Git, merge, and policy code
as trust boundaries.

Before changing behavior, read:

- `README.md`
- `docs/architecture.md`
- `docs/security_model.md`
- `docs/policy.md`
- `CONTRIBUTING.md`

Implementation rules:

- New receipts are schema 3; keep explicit legacy verification isolated.
- Signer metadata belongs inside the signed payload.
- Default fingerprint scope is the full tracked repository; generated inputs
  require explicit extra paths.
- Never turn receipt-emission failures into success unless the caller selected
  `best_effort`.
- Never accept unknown policy fields or malformed receipt structure.
- Keep tests hermetic: mock GitHub key lookup and local identity.
- Maintain 100% line and branch coverage. Add adversarial cases for new trust
  branches.
- Do not edit generated `site/` or release artifacts in `dist/`.

Run the complete check list from `CONTRIBUTING.md` before proposing a PR.
