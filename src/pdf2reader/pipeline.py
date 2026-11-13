"""Coordinate parallel page conversion, book assembly, and output publication."""

import concurrent.futures as cf
import copy
import json
import multiprocessing
import pathlib
import sys

import pymupdf as fitz

from . import export
from .budget import RequestBudget
from .checkpoints import checkpoint_directory, save_checkpoint
from .openai_client import meta_from
from .pages import convert_page, parse_pages


def run(args, work):
    with multiprocessing.Manager() as manager:
        return run_pipeline(args, work, manager)


def run_pipeline(args, work, manager):
    pdf = pathlib.Path(args.src).expanduser().resolve(strict=True)
    output = pathlib.Path(args.out or f"{pdf.stem}-output").expanduser()
    if output.exists() or output.is_symlink():
        raise ValueError(f"output already exists; choose a new directory with -o: {output}")
    with fitz.open(pdf) as doc:
        total = len(doc)
    pages = parse_pages(args.pages, total)
    if not pages:
        raise ValueError("PDF has no pages")
    checkpoints = checkpoint_directory(pdf, args)
    args = copy.copy(args)
    args.budget = RequestBudget(manager, checkpoints, getattr(args, "requests_per_minute", 10),
                                tuple(getattr(args, name, None) for name in
                                      ("input_price", "cached_input_price", "output_price")))
    args.budget.report()
    print(f"Checkpoints: {checkpoints}", file=sys.stderr)
    results = {}
    with cf.ProcessPoolExecutor(args.jobs) as executor:
        futures = {executor.submit(convert_page, pdf, n, total, args, checkpoints): n for n in pages}
        for future in cf.as_completed(futures):
            n, md, figures = future.result()
            results[n] = (md, figures)
            print(f"page {n} complete ({len(results)}/{len(pages)})", file=sys.stderr)

    book, images = None, {}
    for n in pages:
        md, figures = results[n]
        page = export.sanitize_page(md, figures, work)
        if book is None:
            book = page
        else:
            book["blocks"].extend(page["blocks"])
        images.update({name: data for name, data in figures.values()})
    meta = {}
    if args.epub:
        meta_path = checkpoints / f"metadata-{pages[0]}.json"
        if meta_path.is_symlink():
            raise ValueError("metadata checkpoint must not be a symlink")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                if not isinstance(meta, dict) or not all(
                    k in ("title", "author", "date") and isinstance(v, str) for k, v in meta.items()
                ):
                    meta = {}
            except ValueError:
                meta = {}
        if not meta:
            meta = meta_from(results[pages[0]][0], budget=args.budget)
            if meta:
                save_checkpoint(meta_path, meta)
    meta["title"] = args.title or meta.get("title") or pdf.stem
    if args.author:
        meta["author"] = args.author
    book["meta"] = {k: {"t": "MetaString", "c": v} for k, v in meta.items()}
    markdown = export.pandoc(json.dumps(book).encode(), "json", export.MARKDOWN_FORMAT, work)
    epub = None
    if args.epub:
        epub = export.pandoc(json.dumps(export.embedded_ast(book, images)).encode(), "json", "epub3", work,
                             "--mathml", "--toc", "--toc-depth=2", "--split-level=2")

    # A new private directory is created only after conversion succeeds.
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, data in {"book.md": markdown, **images, **({"book.epub": epub} if epub else {})}.items():
        with (output / name).open("xb") as stream:
            stream.write(data)
    print(f"Wrote {output}")
