#!/usr/bin/env python3
"""Build the cover, MkDocs reference, and legacy URLs without touching site/."""
import argparse
import gzip
import html
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_URL = "https://a2r-lab.org/pytest-gpu-proof/"
ASSETS = ("style.css", "main.js", "favicon.svg", "workflow.svg",
          "workflow-mobile.svg", "workshop-abstract.pdf", "provenance.json")


def redirect_page(target, canonical):
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pytest-gpu-proof documentation has moved</title>
<link rel="canonical" href="{html.escape(canonical, quote=True)}">
<script>location.replace({json.dumps(target)} + location.search + location.hash);</script>
</head><body><p>The documentation has moved.
<a href="{html.escape(target, quote=True)}">Continue to this page</a>.</p></body></html>
'''


def assemble(reference, output):
    if output.exists():
        raise ValueError(f"Output already exists; choose a fresh path: {output}")
    # Preserve previous asset and search-index URLs as well as rendered pages.
    shutil.copytree(reference, output)
    shutil.copytree(reference, output / "docs")
    for page in reference.rglob("*.html"):
        relative = page.relative_to(reference)
        if relative.as_posix() in ("index.html", "404.html"):
            continue
        prefix = "../" * (len(relative.parts) - 1)
        path = quote(relative.as_posix(), safe="/")
        (output / relative).write_text(redirect_page(
            prefix + "docs/" + path, PUBLIC_URL + "docs/" + path), encoding="utf-8")
    landing = output / "landing"
    landing.mkdir()
    for name in ASSETS:
        shutil.copyfile(ROOT / "website" / name, landing / name)
    shutil.copyfile(ROOT / "website" / "index.html", output / "index.html")
    (output / ".nojekyll").touch()
    # MkDocs already uses /docs/ canonical URLs. Add the project cover as well.
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", namespace)
    sitemap = ET.parse(reference / "sitemap.xml")
    entry = ET.SubElement(sitemap.getroot(), f"{{{namespace}}}url")
    ET.SubElement(entry, f"{{{namespace}}}loc").text = PUBLIC_URL
    sitemap.write(output / "sitemap.xml", encoding="utf-8", xml_declaration=True)
    with gzip.open(output / "sitemap.xml.gz", "wb") as compressed:
        compressed.write((output / "sitemap.xml").read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "website")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error(f"Output already exists; choose a fresh path: {output}")
    with tempfile.TemporaryDirectory(prefix="gpu-proof-docs-") as scratch:
        reference = Path(scratch) / "reference"
        subprocess.run([sys.executable, "-m", "mkdocs", "build", "--strict",
                        "--site-dir", str(reference)], cwd=ROOT, check=True)
        assemble(reference, output)
    subprocess.run([sys.executable, str(ROOT / "website" / "check_site.py"),
                    str(output)], check=True)
    print(f"Review site: {output}")


if __name__ == "__main__":
    main()
