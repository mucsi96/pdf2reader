"""Sandboxed Pandoc conversion, document sanitization, and image embedding."""

import base64
import copy
import io
import json
import posixpath
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from importlib.resources import files

MARKDOWN_FORMAT = "markdown-raw_html-raw_tex-yaml_metadata_block-implicit_figures"
CODE_LANGUAGES = frozenset({"python", "json", "javascript", "typescript", "bash", "sh",
                            "shell", "sql", "yaml", "toml", "xml", "html", "css", "text",
                            "java", "c", "cpp", "rust", "go", "r", "console", "diff"})


def pandoc(data, source, target, work, *options):
    """Pandoc receives stdin only and has filesystem/network access sandboxed."""
    if target == "epub3":
        # Highlighted span-per-line markup clips and adds gaps in some EPUB
        # renderers. Plain semantic code retains whitespace and reflows reliably.
        options = (*options, "--no-highlight")
    result = subprocess.run(
        [shutil.which("pandoc"), "--sandbox", "-f", source, "-t", target, *options],
        input=data, capture_output=True, cwd=work, timeout=120, check=True,
    )
    return result.stdout


def sanitize_page(md, figures, work):
    """Parse before validation: only exact extracted FIG IDs can become images."""
    ast = json.loads(pandoc(md.encode(), MARKDOWN_FORMAT + "+lists_without_preceding_blankline", "json", work))
    used = set()

    def walk(node):
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        kind, value = node.get("t"), node.get("c")
        if kind in ("RawInline", "RawBlock"):
            return {"t": "Str", "c": ""} if kind == "RawInline" else {"t": "Null"}
        if kind == "Image":
            _, caption, (target, _) = value
            if target not in figures:
                return {"t": "Span", "c": [["", [], []], walk(caption)]}
            used.add(target)
            return {"t": "Image", "c": [["", [], []], walk(caption), [figures[target][0], ""]]}
        if kind == "Link":
            return {"t": "Span", "c": [["", [], []], walk(value[1])]}
        if kind in ("Code", "CodeBlock"):
            value[0] = ["", [name for name in value[0][1] if name in CODE_LANGUAGES], []]
        elif kind in ("Div", "Span", "Table", "Figure"):
            value[0] = ["", [], []]
        elif kind == "Header":
            value[1] = ["", [], []]
        return {key: walk(item) for key, item in node.items()}

    ast["meta"] = {}
    ast["blocks"] = walk(ast["blocks"])
    for target in sorted(figures.keys() - used):
        ast["blocks"].append({"t": "Para", "c": [
            {"t": "Image", "c": [["", [], []], [{"t": "Str", "c": "Figure"}], [figures[target][0], ""]]}]})
    return ast


def embedded_ast(ast, images):
    """Embed only trusted bytes, never open a model-supplied path."""
    def walk(node):
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, dict):
            if node.get("t") == "Image":
                name = node["c"][2][0]
                node["c"][2][0] = "data:image/png;base64," + base64.b64encode(images[name]).decode("ascii")
            return {key: walk(item) for key, item in node.items()}
        return node
    return walk(copy.deepcopy(ast))


def finalize_epub(data, cover=None, publication_date=None):
    """Add a trusted cover without granting Pandoc filesystem access.

    Both EPUB 3 cover-image and EPUB 2 cover metadata are supplied for readers
    such as KOReader. Unknown publication dates are omitted, not set to 1970.
    """
    opf_ns = "http://www.idpf.org/2007/opf"
    dc_ns = "http://purl.org/dc/elements/1.1/"
    container_ns = "urn:oasis:names:tc:opendocument:xmlns:container"
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        container = ET.fromstring(source.read("META-INF/container.xml"))
        package_path = container.find(f".//{{{container_ns}}}rootfile").attrib["full-path"]
        prefix = package_path.rpartition("/")[0]
        prefix = prefix + "/" if prefix else ""
        package = ET.fromstring(source.read(package_path))
        metadata = package.find(f"{{{opf_ns}}}metadata")
        for element in list(metadata):
            if element.tag == f"{{{dc_ns}}}date":
                metadata.remove(element)
        if publication_date:
            ET.SubElement(metadata, f"{{{dc_ns}}}date").text = publication_date

        manifest = package.find(f"{{{opf_ns}}}manifest")
        stylesheet = prefix + "pdf2reader.css"
        ET.SubElement(manifest, f"{{{opf_ns}}}item", {
            "id": "pdf2reader-style", "href": "pdf2reader.css", "media-type": "text/css"})
        added = {stylesheet: files("pdf2reader").joinpath("reader.css").read_bytes()}
        if cover is not None:
            spine = package.find(f"{{{opf_ns}}}spine")
            ET.SubElement(metadata, f"{{{opf_ns}}}meta", {
                "name": "cover", "content": "pdf2reader-cover-image"})
            ET.SubElement(manifest, f"{{{opf_ns}}}item", {
                "id": "pdf2reader-cover-image", "href": "pdf2reader-cover.png",
                "media-type": "image/png", "properties": "cover-image"})
            ET.SubElement(manifest, f"{{{opf_ns}}}item", {
                "id": "pdf2reader-cover-page", "href": "pdf2reader-cover.xhtml",
                "media-type": "application/xhtml+xml"})
            spine.insert(0, ET.Element(f"{{{opf_ns}}}itemref", {
                "idref": "pdf2reader-cover-page"}))
            guide = package.find(f"{{{opf_ns}}}guide")
            if guide is None:
                guide = ET.SubElement(package, f"{{{opf_ns}}}guide")
            ET.SubElement(guide, f"{{{opf_ns}}}reference", {
                "type": "cover", "title": "Cover", "href": "pdf2reader-cover.xhtml"})
            added[prefix + "pdf2reader-cover.png"] = cover
            added[prefix + "pdf2reader-cover.xhtml"] = b'''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Cover</title><style>
html, body { margin: 0; padding: 0; height: 100%; text-align: center; }
img { width: 100%; height: 100vh; object-fit: contain; }
</style></head><body epub:type="cover"><img src="pdf2reader-cover.png" alt="Cover" /></body></html>'''

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
            # EPUB requires the uncompressed mimetype entry to be first.
            target.writestr("mimetype", source.read("mimetype"), compress_type=zipfile.ZIP_STORED)
            for entry in source.infolist():
                if entry.filename == "mimetype":
                    continue
                content = (ET.tostring(package, encoding="utf-8", xml_declaration=True)
                           if entry.filename == package_path else source.read(entry.filename))
                if entry.filename.endswith(".xhtml"):
                    document = ET.fromstring(content)
                    head = document.find("{http://www.w3.org/1999/xhtml}head")
                    if head is not None:
                        ET.SubElement(head, "{http://www.w3.org/1999/xhtml}link", {
                            "rel": "stylesheet", "type": "text/css",
                            "href": posixpath.relpath(stylesheet, posixpath.dirname(entry.filename))})
                        content = ET.tostring(document, encoding="utf-8", xml_declaration=True)
                target.writestr(entry, content)
            for name, content in added.items():
                target.writestr(name, content)
        return output.getvalue()
