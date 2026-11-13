"""Sandboxed Pandoc conversion, document sanitization, and image embedding."""

import base64
import copy
import json
import shutil
import subprocess

MARKDOWN_FORMAT = "markdown-raw_html-raw_tex-yaml_metadata_block"


def pandoc(data, source, target, work, *options):
    """Pandoc receives stdin only and has filesystem/network access sandboxed."""
    result = subprocess.run(
        [shutil.which("pandoc"), "--sandbox", "-f", source, "-t", target, *options],
        input=data, capture_output=True, cwd=work, timeout=120, check=True,
    )
    return result.stdout


def sanitize_page(md, figures, work):
    """Parse before validation: only exact extracted FIG IDs can become images."""
    ast = json.loads(pandoc(md.encode(), MARKDOWN_FORMAT, "json", work))
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
        if kind in ("Code", "CodeBlock", "Div", "Span", "Table", "Figure"):
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
