# Contributing

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Required checks

```bash
python -m pytest tests -q
coverage run -m pytest tests -q
coverage report --fail-under=100
mkdocs build --strict
python -m build
python -m twine check --strict dist/*
```

CI runs the test suite on Python 3.11, 3.12, and 3.13, independently enforces
100% line and branch coverage, builds docs strictly, and smoke-tests the wheel.

## Change expectations

- Add adversarial tests for trust-boundary changes, not only happy paths.
- Keep receipt generation and verification fail-closed by default.
- Treat schema and policy changes as compatibility decisions; document them in
  `CHANGELOG.md` and the relevant guide.
- Keep Git and network tests hermetic. Never depend on a developer's actual
  GitHub login, SSH keys, GPU, or global Git configuration.
- Use separate pytest processes for shards. Receipt generation does not support
  xdist workers.
- Do not commit generated `site/`, coverage files, caches, or local receipts.

## Pull requests

Describe the trust claim before and after the change, migration implications,
and the exact checks run. Small, reviewable commits are preferred. Security
reports should follow [SECURITY.md](SECURITY.md), not a public issue.
