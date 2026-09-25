# Project website

The cover is designed for `https://a2r-lab.org/pytest-gpu-proof/`, with MkDocs
under `/docs/`. This review branch does not publish the site or change plugin
behavior. The source, receipt, signature, and policy trust boundaries are unchanged.

## Pull and preview

Save local changes before switching branches. From an existing checkout:

```sh
git fetch origin
git switch codex/gpu-proof-website
git pull --ff-only origin codex/gpu-proof-website
```

For a new checkout:

```sh
git clone --branch codex/gpu-proof-website https://github.com/A2R-Lab/pytest-gpu-proof.git
cd pytest-gpu-proof
```

Build and serve locally. No GPU, signing key, or LaTeX installation is needed:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r website/requirements.txt
preview_dir=$(mktemp -d)
python website/build_site.py --output "$preview_dir/pytest-gpu-proof"
python -m http.server 8000 --bind 127.0.0.1 --directory "$preview_dir"
```

Open `http://localhost:8000/pytest-gpu-proof/` for the cover and
`http://localhost:8000/pytest-gpu-proof/docs/` for documentation.
Stop with Ctrl+C. The builder performs a strict MkDocs build and checks links,
fragments, redirects, and arXiv references. It refuses an existing output
directory, so use a fresh `preview_dir` after each pull. It does not modify the
generated `site/` directory. Relative paths also work at the repository URL prefix.

## Deployment and legacy URLs

The Docs workflow builds and checks on pull requests, but publishes only after
a push to `main`. It preserves the existing `gh-pages` branch deployment method.
The repository must have Pages enabled with **Deploy from a branch**, using
`gh-pages` and `/ (root)`. At implementation time both public URLs returned 404
and the Pages API did not report an active site. No hosting settings were changed.
Confirm the actual public URL when enabling Pages and, if different, update
the canonical URLs in `index.html`, `build_site.py`, `mkdocs.yml`, and package metadata.

Old `/quickstart/`, `/policy/`, and other documentation URLs redirect under
`/docs/`, preserving queries and fragments. Assets remain at their old paths.
Old homepage section bookmarks redirect to the corresponding docs homepage.
The docs announcement bar returns to the cover during local and hosted previews.
The preview uses the repository URL prefix so MkDocs' production-rooted 404
assets also resolve locally.

Website regression checks can be run with
`python -m unittest discover -s website -p 'test_*.py'`.

## Paper and figure provenance

The paper is hosted on [arXiv](https://arxiv.org/abs/2609.28862). The cover,
resource buttons, PDF link, citation, and metadata all point there. No local
copy of the abstract is stored or distributed with the site.

The desktop and mobile SVGs adapt the single TikZ figure in `workshop_main.tex`
from the original `glass-paper` repository. `provenance.json` retains that source
commit and hash alongside the arXiv identifier. The SVGs use the current
tool's broader SSH-signing terminology and preserve the signer trust boundary.
The web text follows the current README and security model where these are more
precise than the workshop summary. The source repository was not changed.

## Updating the paper link

The links use the version-independent arXiv URL. If the identifier changes,
update the hero, figure link, paper resource links, BibTeX, and citation metadata
in `index.html` together with `provenance.json`. Keep downloads hosted on arXiv.

## Design attribution

The cover shares GLASS/GATO typography, green accents, resource buttons, and
cards. The footer preserves attribution to GLASS, GATO, and Nerfies under
CC BY-SA 4.0. Plugin licensing remains MIT.
