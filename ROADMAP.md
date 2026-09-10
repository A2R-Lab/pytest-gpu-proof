# Roadmap

The current focus is a small, auditable receipt format and strict local-to-CI
workflow. Candidate future work:

- SSHSIG-compatible signing, SSH-agent signing, and hardware-backed keys;
- optional verification of every input shard signature before merge;
- CI-issued nonce/challenge mode for stronger replay resistance;
- Sigstore/OIDC provenance for controlled CI-GPU runs;
- archived signer-key evidence or transparency integration;
- versioned JSON Schema publication and external conformance fixtures;
- an explicit multi-machine merge model for heterogeneous GPU metadata.

Hardware execution attestation is intentionally out of scope unless a concrete
backend and verifier can support claims stronger than self-reported GPU data.
