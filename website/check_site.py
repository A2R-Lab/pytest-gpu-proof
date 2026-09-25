#!/usr/bin/env python3
"""Check rendered links, fragments, legacy redirects, and arXiv references."""
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.links = []
        self.ids = set()
        self.metadata = {}
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and "name" in attrs:
            self.metadata[attrs["name"]] = attrs.get("content", "")
        if "id" in attrs:
            self.ids.add(attrs["id"])
        for key in ("href", "src"):
            if key in attrs:
                self.links.append(attrs[key])
        if "srcset" in attrs:
            self.links.extend(item.strip().split()[0]
                              for item in attrs["srcset"].split(","))


def check(root):
    pages = {path.resolve(): Page(path.read_text(encoding="utf-8"))
             for path in root.rglob("*.html")}
    errors = []
    for path, page in pages.items():
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            # MkDocs 404 pages use the deployment prefix for absolute assets.
            local_path = url.path.removeprefix("/pytest-gpu-proof/")
            target = (root / unquote(local_path.lstrip("/")) if url.path.startswith("/")
                      else path.parent / unquote(url.path)) if url.path else path
            if target.is_dir():
                target /= "index.html"
            target = target.resolve()
            if not target.exists():
                errors.append(f"{path.relative_to(root)}: missing {link}")
            elif url.fragment and target in pages:
                if unquote(url.fragment) not in pages[target].ids:
                    errors.append(f"{path.relative_to(root)}: missing anchor {link}")
    for doc in (root / "docs").rglob("*.html"):
        rel = doc.relative_to(root / "docs")
        if rel.as_posix() in ("index.html", "404.html"):
            continue
        legacy = root / rel
        source = legacy.read_text(encoding="utf-8")
        if "location.search + location.hash" not in source:
            errors.append(f"Legacy query/fragment preservation missing: {rel}")
        if not any((legacy.parent / unquote(urlsplit(link).path)).resolve() == doc.resolve()
                   for link in pages[legacy.resolve()].links):
            errors.append(f"Legacy redirect target mismatch: {rel}")
    manifest = json.loads((root / "landing" / "provenance.json").read_text())
    cover_page = pages[(root / "index.html").resolve()]
    paper_url = manifest["paper_url"]
    expected_metadata = {
        "citation_arxiv_id": manifest["arxiv_id"],
        "citation_abstract_html_url": paper_url,
        "citation_pdf_url": paper_url.replace("/abs/", "/pdf/"),
    }
    for key, value in expected_metadata.items():
        if cover_page.metadata.get(key) != value:
            errors.append(f"arXiv metadata mismatch: {key}")
    if paper_url not in cover_page.links:
        errors.append("arXiv paper link is missing")
    cover = (root / "index.html").read_text(encoding="utf-8")
    if f'eprint={{{manifest["arxiv_id"]}}}' not in cover or f'url={{{paper_url}}}' not in cover:
        errors.append("arXiv citation mismatch")
    if "arXiv forthcoming" in cover:
        errors.append("Stale arXiv placeholder")
    if (root / "landing" / "workshop-abstract.pdf").exists() or "workshop-abstract.pdf" in cover:
        errors.append("Local abstract PDF must not be distributed or linked")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"PASS: {len(pages)} HTML pages; local links, fragments, redirects, and arXiv references")


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve())
