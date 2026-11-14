import argparse
import concurrent.futures
import io
import json
import pathlib
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import patch

import pymupdf as fitz

from pdf2reader import export, openai_client, pipeline
from pdf2reader.checkpoints import checkpoint_directory
from pdf2reader.pages import convert_page, figure_regions, unwrap_markdown


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.pdf = self.root / "input.pdf"
        with fitz.open() as doc:
            for number in (1, 2):
                page = doc.new_page()
                page.insert_text((72, 72), f"Page {number}")
                page.draw_rect(fitz.Rect(80, 100, 300, 300))
            doc.save(self.pdf)
            self.png = doc[0].get_pixmap().tobytes("png")
        self.args = argparse.Namespace(src=str(self.pdf), out=str(self.root / "output"),
                                      work_dir=str(self.root / "work"), jobs=1, dpi=72,
                                      fig_dpi=72, images=True, pages=None, epub=True,
                                      title=None, author=None)

    def test_failed_ai_page_resumes_without_repeating_success(self):
        checkpoints = checkpoint_directory(self.pdf, self.args)
        success = subprocess.CompletedProcess([], 0, "# Chapter\n\nText", "")
        failure = subprocess.CompletedProcess([], 1, "", "temporary failure")
        with patch.object(openai_client, "llm", side_effect=[success, failure]) as api:
            first = convert_page(self.pdf, 1, 2, self.args, checkpoints)
            with self.assertRaisesRegex(RuntimeError, "page 2 failed"):
                convert_page(self.pdf, 2, 2, self.args, checkpoints)
            self.assertEqual(api.call_count, 2)
        self.assertFalse((checkpoints / "page-2.json").exists())
        with patch.object(openai_client, "llm", return_value=success) as api:
            self.assertEqual(convert_page(self.pdf, 1, 2, self.args, checkpoints), first)
            convert_page(self.pdf, 2, 2, self.args, checkpoints)
            self.assertEqual(api.call_count, 1)
        self.args.dpi = 80
        self.assertNotEqual(checkpoint_directory(self.pdf, self.args), checkpoints)
        self.assertEqual(list(checkpoints.glob("page-*-*")), [])

    def test_blank_page_resumes_without_api_calls(self):
        blank = self.root / "blank.pdf"
        with fitz.open() as doc:
            doc.new_page()
            doc.save(blank)
        checkpoints = checkpoint_directory(blank, self.args)
        with patch.object(openai_client, "llm", side_effect=AssertionError("blank page sent to AI")):
            self.assertEqual(convert_page(blank, 1, 1, self.args, checkpoints), (1, "", {}))
            with patch("pdf2reader.pages.render_page", side_effect=AssertionError("checkpoint not reused")):
                self.assertEqual(convert_page(blank, 1, 1, self.args, checkpoints), (1, "", {}))

    def test_refresh_replaces_only_successful_page_checkpoint(self):
        checkpoints = checkpoint_directory(self.pdf, self.args)
        with patch.object(openai_client, "llm", return_value=subprocess.CompletedProcess([], 0, "Old", "")):
            convert_page(self.pdf, 1, 2, self.args, checkpoints)
        self.args.refresh_pages = {1}
        with patch.object(openai_client, "llm", return_value=subprocess.CompletedProcess([], 1, "", "failed")):
            with self.assertRaises(RuntimeError):
                convert_page(self.pdf, 1, 2, self.args, checkpoints)
        self.assertEqual(json.loads((checkpoints / "page-1.json").read_text())["markdown"], "Old")
        with patch.object(openai_client, "llm", return_value=subprocess.CompletedProcess([], 0, "New", "")):
            convert_page(self.pdf, 1, 2, self.args, checkpoints)
        self.assertEqual(json.loads((checkpoints / "page-1.json").read_text())["markdown"], "New")

    def test_code_fences_are_not_stripped(self):
        for md in ("```python\ndef f():\n    return 1\n```", "Text\n\n```json\n{}\n```",
                   "```\nunknown language code\n```", "    indented code"):
            with self.subTest(markdown=md):
                self.assertEqual(unwrap_markdown(md), md)
        self.assertEqual(unwrap_markdown("````markdown\n```python\nprint(1)\n```\n````"),
                         "```python\nprint(1)\n```")

    def test_code_boxes_are_not_extracted_as_figures(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.draw_rect(fitz.Rect(50, 50, 500, 200), fill=(0.95, 0.95, 0.95))
            page.insert_text((65, 80), "def example():\n    return 42", fontname="cour")
            page.draw_rect(fitz.Rect(80, 300, 300, 500))
            regions = figure_regions(page)
            self.assertEqual(len(regions), 1)
            self.assertGreater(regions[0].y0, 200)

    def test_text_tables_are_not_extracted_as_figures(self):
        with fitz.open() as doc:
            page = doc.new_page()
            for y in (80, 130, 180):
                page.draw_line((50, y), (450, y))
            for x in (50, 250, 450):
                page.draw_line((x, 80), (x, 180))
            for point, text in (((60, 105), "Name"), ((260, 105), "Value"),
                                ((60, 155), "Example"), ((260, 155), "42")):
                page.insert_text(point, text)
            self.assertEqual(figure_regions(page), [])

    def test_figure_alt_does_not_duplicate_printed_caption(self):
        ast = export.sanitize_page("![A diagram](FIG_1)\n\n*Figure 1 — A diagram*",
                                   {"FIG_1": ("p1-1.png", self.png)}, self.root)
        self.assertEqual([node["t"] for node in ast["blocks"]], ["Para", "Para"])
        self.assertEqual(ast["blocks"][0]["c"][0]["t"], "Image")

    def test_code_reflows_without_clipping_on_small_screens(self):
        md = ("```python\nfrom example import ConversationBufferMemory, ConversationSummaryMemory\n"
              "def example():\n    update_user_preferences(interaction_data[\"user_id\"], success_score)\n"
              "    return 'A long string with spaces that must wrap instead of clipping'\n```\n")
        ast = export.sanitize_page(md, {}, self.root)
        epub = export.finalize_epub(export.pandoc(json.dumps(ast).encode(), "json", "epub3", self.root))
        with zipfile.ZipFile(io.BytesIO(epub)) as archive:
            ns = {"h": "http://www.w3.org/1999/xhtml"}
            for name in archive.namelist():
                if name.endswith(".xhtml"):
                    doc = ET.fromstring(archive.read(name))
                    for code in doc.findall(".//h:pre/h:code", ns):
                        self.assertEqual(len(code), 0)  # no span-per-line highlighting
                        self.assertIn("\n    return", code.text)
        path = self.root / "layout.epub"
        path.write_bytes(epub)
        for width in (320, 450):
            with self.subTest(width=width), fitz.open(path) as doc:
                doc.layout(width=width, height=650, fontsize=12)
                for page in doc:
                    for word in page.get_text("words"):
                        self.assertGreaterEqual(word[0], -1)
                        self.assertLessEqual(word[2], width + 1)

    def test_semantic_formatting_survives_export(self):
        md = '''**Bold**, *italic*, and `inline_code`.

> Quoted text.

4. Fourth item
5. Fifth item

```python
def example():
    return "<literal>"
```

| Name | Value |
|---|---|
| A | 42 |
'''
        ast = export.sanitize_page(md, {}, self.root)
        block = next(b for b in ast["blocks"] if b["t"] == "CodeBlock")
        self.assertEqual(block["c"][0], ["", ["python"], []])
        self.assertIn('    return "<literal>"', block["c"][1])
        epub = export.finalize_epub(export.pandoc(json.dumps(ast).encode(), "json", "epub3", self.root))
        with zipfile.ZipFile(io.BytesIO(epub)) as archive:
            documents = [ET.fromstring(archive.read(name)) for name in archive.namelist() if name.endswith(".xhtml")]
            tags = {node.tag.split("}")[-1] for doc in documents for node in doc.iter()}
            self.assertTrue({"strong", "em", "code", "pre", "blockquote", "ol", "li", "table", "td"} <= tags)
            self.assertTrue(any(node.attrib.get("start") == "4" for doc in documents for node in doc.iter()))
            self.assertTrue(any(name.endswith("pdf2reader.css") for name in archive.namelist()))
            self.assertTrue(all(any(node.attrib.get("href", "").endswith("pdf2reader.css")
                                    for node in doc.iter()) for doc in documents))

    def test_malicious_references_cannot_reach_epub(self):
        secret = self.root / "secret.png"
        secret.write_bytes(b"DO_NOT_EXPORT_THIS_FILE")
        md = f'''# Chapter

![allowed](FIG_1)
![local]({secret})
![traversal](../secret.png)
![remote](https://example.invalid/collect)
![reference][evil]

[evil]: file://{secret}

<script>alert(1)</script>
<img src="{secret}" onerror="alert(1)">
[click](javascript:alert(1))
[styled]{{onclick="alert(1)"}}

Math $x^2$ and a footnote.[^1]

[^1]: Note text.

| A | B |
|---|---|
| 1 | 2 |
'''
        ast = export.sanitize_page(md, {"FIG_1": ("p1-1.png", self.png)}, self.root)
        embedded = export.embedded_ast(ast, {"p1-1.png": self.png})
        epub = export.pandoc(json.dumps(embedded).encode(), "json", "epub3", self.root, "--mathml", "--toc")
        with zipfile.ZipFile(io.BytesIO(epub)) as archive:
            contents = b"\n".join(archive.read(name) for name in archive.namelist())
            self.assertNotIn(b"DO_NOT_EXPORT_THIS_FILE", contents)
            xhtml = b"\n".join(archive.read(name) for name in archive.namelist() if name.endswith(".xhtml"))
            for name in archive.namelist():
                if name.endswith(".xhtml"):
                    for element in ET.fromstring(archive.read(name)).iter():
                        self.assertNotEqual(element.tag.split("}")[-1], "script")
                        self.assertFalse(any(key.lower().startswith("on") for key in element.attrib))
                        self.assertFalse(any(value.startswith(("file:", "javascript:", "https://example.invalid"))
                                             for value in element.attrib.values()))
            self.assertIn(b"<math", xhtml)
            self.assertIn(b"<table", xhtml)
            self.assertIn(b"Note text", xhtml)
            self.assertEqual([archive.read(name) for name in archive.namelist() if name.endswith(".png")], [self.png])

    def test_lists_without_blank_lines_preserve_nesting(self):
        ast = export.sanitize_page("**Frameworks**\n- LangChain\n  - Tools\n- AutoGen", {}, self.root)
        self.assertEqual([block["t"] for block in ast["blocks"]], ["Para", "BulletList"])
        items = ast["blocks"][1]["c"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0][1]["t"], "BulletList")

    def test_epub_cover_and_publication_date(self):
        original = export.pandoc(b"# Title\n\nText", "markdown", "epub3", self.root)
        ns = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
        for date in (None, "2026-03"):
            with self.subTest(date=date):
                result = export.finalize_epub(original, self.png, date)
                with zipfile.ZipFile(io.BytesIO(result)) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertEqual(archive.infolist()[0].filename, "mimetype")
                    self.assertEqual(archive.infolist()[0].compress_type, zipfile.ZIP_STORED)
                    package_path = next(name for name in archive.namelist() if name.endswith(".opf"))
                    package = ET.fromstring(archive.read(package_path))
                    dates = package.findall("opf:metadata/dc:date", ns)
                    self.assertEqual([element.text for element in dates], [date] if date else [])
                    cover = package.find("opf:manifest/opf:item[@properties='cover-image']", ns)
                    self.assertIsNotNone(cover)
                    image_path = pathlib.PurePosixPath(package_path).parent / cover.attrib["href"]
                    self.assertEqual(archive.read(str(image_path)), self.png)
                    legacy = package.find("opf:metadata/opf:meta[@name='cover']", ns)
                    self.assertEqual(legacy.attrib["content"], cover.attrib["id"])
                    first = package.find("opf:spine/opf:itemref", ns)
                    self.assertEqual(first.attrib["idref"], "pdf2reader-cover-page")
                    for name in archive.namelist():
                        if name.endswith((".xhtml", ".opf", ".xml")):
                            ET.fromstring(archive.read(name))

    def test_epub_xhtml_keeps_unprefixed_tags_for_koreader(self):
        original = export.pandoc(b"# Chapter\n\nMath $x^2$ and `code`.\n", "markdown", "epub3",
                                 self.root, "--mathml", "--toc")
        result = export.finalize_epub(original, self.png, "2026-03")
        with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(io.BytesIO(result)) as output:
            for name in source.namelist():
                if name.endswith(".xhtml"):
                    xhtml = output.read(name)
                    self.assertIn(b"<html ", xhtml)
                    self.assertRegex(xhtml, rb"<body(?:\s|>)")
                    self.assertNotRegex(xhtml, rb"</?\w+:(?:html|head|body|section|p)\b")
                    # Preserve all markup, including MathML namespaces, except
                    # for the one trusted stylesheet link added to the head.
                    restored, count = re.subn(rb'<link rel="stylesheet" type="text/css" href="[^"]*pdf2reader\.css" />',
                                              b"", xhtml)
                    self.assertEqual(count, 1)
                    self.assertEqual(restored, source.read(name))
            package = output.read(next(name for name in output.namelist() if name.endswith(".opf")))
            self.assertIn(b'<package xmlns="http://www.idpf.org/2007/opf"', package)

    def test_full_pipeline_and_resume_after_export_failure(self):
        def fake_ai(prompt, **kwargs):
            if "Return ONLY JSON" in prompt:
                text = '{"title":"Test book","author":"Writer","date":""}'
            else:
                text = "# Chapter\n\nParagraph with math $x^2$.\n\n![Figure](FIG_1)"
            return subprocess.CompletedProcess([], 0, text, "")

        original = export.pandoc
        def fail_epub(data, source, target, work, *options):
            if target == "epub3":
                raise RuntimeError("export interrupted")
            return original(data, source, target, work, *options)

        # One worker keeps native PDF rendering serial in this in-process test.
        with patch.object(pipeline.cf, "ProcessPoolExecutor", concurrent.futures.ThreadPoolExecutor):
            with patch.object(openai_client, "llm", side_effect=fake_ai) as api, patch.object(export, "pandoc", side_effect=fail_epub):
                with self.assertRaisesRegex(RuntimeError, "export interrupted"):
                    pipeline.run(self.args, self.root)
                self.assertEqual(api.call_count, 3)  # two pages + metadata
            self.assertFalse(pathlib.Path(self.args.out).exists())
            with patch.object(openai_client, "llm", side_effect=AssertionError("AI call repeated")):
                pipeline.run(self.args, self.root)
        output = pathlib.Path(self.args.out)
        self.assertTrue((output / "book.md").exists())
        self.assertTrue((output / "book.md").read_text().startswith("![Cover](cover.png)"))
        with fitz.open(self.pdf) as doc:
            self.assertEqual((output / "cover.png").read_bytes(),
                             doc[0].get_pixmap(dpi=self.args.fig_dpi).tobytes("png"))
        with zipfile.ZipFile(output / "book.epub") as archive:
            self.assertEqual(archive.read("mimetype"), b"application/epub+zip")
        marker = output / "unrelated.txt"
        marker.write_text("keep me")
        with self.assertRaisesRegex(ValueError, "output already exists"):
            pipeline.run(self.args, self.root)
        self.assertEqual(marker.read_text(), "keep me")
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
