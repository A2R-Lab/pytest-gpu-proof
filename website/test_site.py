"""CPU-only regression checks for the website build and release checks."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_site import ROOT, assemble, redirect_page
from check_site import Page, check


class WebsiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="gpu-proof-website-tests-")
        cls.built = Path(cls.scratch.name) / "built"
        subprocess.run([sys.executable, str(ROOT / "website" / "build_site.py"),
                        "--output", str(cls.built)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(prefix="gpu-proof-website-case-")
        self.addCleanup(self.case.cleanup)
        self.site = Path(self.case.name) / "site"
        shutil.copytree(self.built, self.site)

    def test_complete_site(self):
        check(self.site)
        sitemap = (self.site / "sitemap.xml").read_text()
        self.assertIn("https://a2r-lab.org/pytest-gpu-proof/</loc>", sitemap)
        self.assertIn("https://a2r-lab.org/pytest-gpu-proof/docs/", sitemap)

    def test_existing_output_is_not_overwritten(self):
        with self.assertRaisesRegex(ValueError, "Output already exists"):
            assemble(self.site / "docs", self.site)

    def test_missing_page_fails(self):
        (self.site / "docs" / "policy" / "index.html").unlink()
        with self.assertRaisesRegex(SystemExit, "missing"):
            check(self.site)

    def test_missing_fragment_fails(self):
        index = self.site / "index.html"
        index.write_text(index.read_text().replace('href="#trust"', 'href="#missing"'))
        with self.assertRaisesRegex(SystemExit, "missing anchor"):
            check(self.site)

    def test_changed_paper_fails(self):
        (self.site / "landing" / "workshop-abstract.pdf").write_bytes(b"not the paper")
        with self.assertRaisesRegex(SystemExit, "provenance manifest"):
            check(self.site)

    def test_legacy_query_and_fragment_guard(self):
        legacy = self.site / "quickstart" / "index.html"
        legacy.write_text(legacy.read_text().replace("location.search + location.hash", "''"))
        with self.assertRaisesRegex(SystemExit, "preservation missing"):
            check(self.site)

    def test_mobile_source_is_checked(self):
        (self.site / "landing" / "workflow-mobile.svg").unlink()
        with self.assertRaisesRegex(SystemExit, "workflow-mobile.svg"):
            check(self.site)

    def test_redirect_escaping(self):
        target = '../docs/a?x=1&y="2"'
        source = redirect_page(target, 'https://example.org/?x="y"')
        self.assertIn(target, Page(source).links)
        self.assertIn("location.search + location.hash", source)
        self.assertIn("&quot;", source)


if __name__ == "__main__":
    unittest.main()
