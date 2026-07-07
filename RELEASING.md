# Releasing pytest-gpu-proof

Publishing runs through GitHub Actions **OIDC trusted publishing** — no PyPI
tokens are stored anywhere. `.github/workflows/publish.yml` has two lanes:

- **TestPyPI** — manual `workflow_dispatch` of the Publish workflow (dry-run lane).
- **PyPI** — automatic on a published GitHub release.

Both lanes build sdist + wheel, run `twine check --strict`, and smoke-test the
wheel (CLI entry point, import, pytest plugin registration) before uploading.

## One-time setup (repo owner, web UI)

1. **PyPI** (pypi.org → account → Publishing → "Add a new pending publisher"):
   - PyPI project name: `pytest-gpu-proof`
   - Owner: `A2R-Lab`, Repository: `pytest-gpu-proof`
   - Workflow name: `publish.yml`
   - Environment: `pypi`
2. **TestPyPI** (test.pypi.org, same form) with environment `testpypi`.
3. **GitHub** (repo → Settings → Environments): create environments `pypi` and
   `testpypi`. Optionally add yourself as a required reviewer on `pypi` so
   every real publish needs a click of approval.

The first trusted-publisher upload CREATES the project on (Test)PyPI and
registers the name — no separate name registration step.

## Per release

1. Update `version` in `pyproject.toml` and retitle the `unreleased` section
   in `CHANGELOG.md` with the date. Commit via the normal branch → PR → CI
   green → merge flow.
2. Dry run: Actions → Publish → "Run workflow" (publishes to TestPyPI), then
   `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ pytest-gpu-proof`
   in a scratch venv and run `gpu-proof --help`.
3. Tag + release:
   ```bash
   git tag v0.X.Y && git push origin v0.X.Y
   gh release create v0.X.Y --title "v0.X.Y" --notes-file <(sed -n '/^## \[0.X.Y\]/,/^## \[/p' CHANGELOG.md | head -n -1)
   ```
   The release event publishes to PyPI.
4. Sanity: `pip install pytest-gpu-proof==0.X.Y` in a scratch venv.

## Versioning

Pre-1.0 SemVer: patch = fixes, minor = features or breaking changes (called
out in the CHANGELOG). Consumers pinning the git submodule are unaffected by
PyPI releases; keep the two install paths (git submodule, PyPI) documented in
the README.
