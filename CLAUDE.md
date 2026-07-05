# CLAUDE.md — orientation for AI agents (and humans) working on pytest-gpu-proof

pytest-gpu-proof is a **pytest plugin that emits a signed JSON receipt of a GPU
test run** (git SHA + source fingerprint + per-test outcomes + GPU info), plus a
**CPU-only verifier** (`gpu-proof verify`) that checks the signature against the
signer's public `github.com/<user>.keys`. The point: run GPU tests on your own
hardware, let CI prove who attested them — no cloud-GPU fees, no secrets in CI.

**Trust model — never oversell it:** a receipt is a **signed attestation by a
keyholder, NOT cryptographic proof of GPU execution**. `gpu_info` is
self-reported; `--require-gpu` is modest hardening against accidents, not
against a dishonest signer. `docs/security_model.md` is the honest statement of
what is and isn't proven — keep every README/docs claim consistent with it.

## Source layout (`src/pytest_gpu_proof/`)

| Module | Role |
|---|---|
| `plugin.py` | pytest hooks: options, `gpu_proof` marker, `gpu_proof_check` fixture, outcome+skip capture, receipt emission at session end |
| `receipt.py` | payload build (repo/fingerprint/tests/env), canonical JSON, sign+write. Signer resolution: flag/config → `gh` CLI login (keyholder) → origin-remote owner (warned — orgs have no SSH keys) |
| `verify.py` | the 7 verification checks (signature, fingerprint, commit SHA, outcomes+skip policy, gpu_info, freshness, dirty policy). Expected-skips baseline = EXACT set match |
| `cli.py` | `gpu-proof verify` argument surface |
| `config.py` | `GpuProofConfig`; CLI flags override `[tool.gpu_proof]` in pyproject.toml |
| `fingerprint.py` | SHA-256 digest over configured paths |
| `gitutils.py` | git/gh shell-outs, all failure-tolerant (return `None`) |
| `signers/` | `base.py` protocol + `ed25519.py` SSH-key signing / GitHub-keys verification; backend `none` emits unsigned receipts |
| `compare.py` | receipt diffing |

Signing covers the canonical (compact, sorted-key) JSON **without** the
`signature` field; the sig block carries `signer`, key fingerprint, algorithm
(derived from actual key type — don't hardcode ed25519).

## Behavioral invariants (test-enforced — don't regress)

- **Skips prove nothing.** Verifier rejects receipts with skips unless
  `--allow-skipped` (any skips) or `--expected-skips` (EXACT baseline: a new
  skip fails, a stale baseline entry fails). The two are mutually exclusive.
- **Unsigned receipts** verify only with `--allow-unsigned`, loudly.
- **`--max-age-days 0`** means "today only", not "disabled".
- The signer recorded at signing time must be the **keyholder**, never
  silently the repo owner.

## Dev workflow

```bash
.venv/bin/python -m pytest tests/ -q      # full suite, ~2s, no GPU needed
.venv/bin/mkdocs build --strict           # docs must stay warning-clean
```

- Tests are **hermetic**: `tests/conftest.py` has an autouse fixture nulling
  `get_gh_cli_login` (a dev box with authenticated `gh` would otherwise hit the
  network). Signer tests re-patch explicitly. Keep new shell-outs mockable and
  wrapped in try/except like `gitutils._git`.
- `tests/conftest.py` uses `pytest_plugins = ["pytester"]`; keypairs are
  generated in-memory (no real SSH keys touched).
- requires-python ≥ 3.11 (`datetime.UTC`).
- CI (`.github/workflows/`): tests on 3.11/3.12 + mkdocs gh-pages deploy.

## Conventions & state

- Short single-line commit messages; no Co-Authored-By footer.
- Flow: feature branch → PR → CI green → merge to `main`. Consumers install
  from git (`pip install -e` on a submodule); **PyPI is deferred** — see
  `ROADMAP.md`, it's its own carefully-planned session.
- Reference integration: **GLASS** (github.com/A2R-Lab/GLASS) —
  `test/run_gpu_proof.sh`, `test/expected_skips.txt`,
  `.github/workflows/verify-gpu-proof.yml`. If you change plugin/verifier
  flags, check GLASS's usage still works and note it in the PR.
- Consumer-side gotcha worth remembering: a repo that submodules this project
  under its pytest rootdir must `collect_ignore = ["pytest-gpu-proof"]` in its
  conftest, or this repo's `tests/conftest.py` will shadow theirs.
