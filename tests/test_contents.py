import concurrent.futures
import pathlib
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from argparse import Namespace
from unittest.mock import patch

import pymupdf as fitz

from pdf2reader import pipeline
from pdf2reader.checkpoints import checkpoint_directory, save_checkpoint
from pdf2reader.contents import printed_contents_pages


class ContentsTests(unittest.TestCase):
    def test_outline_excludes_only_printed_contents_section(self):
        with fitz.open() as doc:
            for _ in range(5):
                doc.new_page()
            doc.set_toc([[1, "Title", 1], [1, "Table of Contents", 2],
                         [2, "Continuation", 3], [1, "Preface", 4], [1, "Chapter", 5]])
            self.assertEqual(printed_contents_pages(doc), {2, 3})

    def test_text_fallback_does_not_remove_prose_about_contents(self):
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 72), "Table of Contents\nFirst ........ 1\nSecond ........ 12")
            doc.new_page().insert_text((72, 72), "Chapter 1\nRefer to the table of contents for an overview.")
            doc.new_page().insert_text((72, 72), "Contents\nThis section discusses the contents of a database.")
            doc.set_toc([[1, "Table of Contents", 1]])  # no reliable end boundary
            self.assertEqual(printed_contents_pages(doc), {1})

    def test_epub_uses_live_navigation_without_printed_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            pdf = root / "book.pdf"
            with fitz.open() as doc:
                for _ in range(4):
                    doc.new_page()
                doc.set_toc([[1, "Title", 1], [1, "Contents", 2],
                             [1, "Actual chapter", 3], [1, "Another chapter", 4]])
                doc.save(pdf)
            args = Namespace(src=str(pdf), out=str(root / "output"), work_dir=str(root / "work"),
                             pages=None, jobs=1, dpi=72, fig_dpi=72, images=False,
                             epub=True, title="Book", author=None)
            directory = checkpoint_directory(pdf, args)
            for n, markdown in enumerate(("# Title", "# Table of Contents\n\nPRINTED-ONLY-ENTRY ... 99",
                                          "# Actual chapter\n\nActual content.", "# Another chapter\n\nMore content."), 1):
                save_checkpoint(directory / f"page-{n}.json", {"markdown": markdown, "figures": {}})
            save_checkpoint(directory / "metadata-1.json", {"title": "Book"})
            with patch.object(pipeline.cf, "ProcessPoolExecutor", concurrent.futures.ThreadPoolExecutor):
                pipeline.run(args, root)
            output = pathlib.Path(args.out)
            self.assertIn("PRINTED-ONLY-ENTRY", (output / "book.md").read_text())
            with zipfile.ZipFile(output / "book.epub") as archive:
                xhtml = [archive.read(name) for name in archive.namelist() if name.endswith(".xhtml")]
                self.assertNotIn(b"PRINTED-ONLY-ENTRY", b"".join(xhtml))
                ns = {"h": "http://www.w3.org/1999/xhtml"}
                nav = ET.fromstring(archive.read("EPUB/nav.xhtml"))
                entries = {"".join(link.itertext()): link.attrib["href"]
                           for link in nav.findall(".//h:nav[@id='toc']//h:a", ns)}
                self.assertIn("Actual chapter", entries)
                self.assertIn("Another chapter", entries)
                self.assertNotIn("Table of Contents", entries)
                for href in entries.values():
                    filename, _, anchor = href.partition("#")
                    document = ET.fromstring(archive.read("EPUB/" + filename))
                    if anchor:
                        self.assertTrue(any(node.attrib.get("id") == anchor for node in document.iter()))
