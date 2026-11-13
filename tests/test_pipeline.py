import argparse
import concurrent.futures
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import patch

import pymupdf as fitz

from pdf2reader import export, openai_client, pipeline
from pdf2reader.checkpoints import checkpoint_directory
from pdf2reader.pages import convert_page


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
