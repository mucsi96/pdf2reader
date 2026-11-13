# pdf2reader

Convert a **local PDF** into clean Markdown and EPUB using **OpenAI GPT-6.1 Sol**.

## Pipeline

1. Rasterize pages with PyMuPDF and extract figure crops.
2. Process pages in parallel using the OpenAI Responses API. The model and endpoint
   are fixed; reasoning effort uses the API default.
3. Parse page Markdown into a Pandoc document tree. Only generated figure IDs can
   become images; links, raw HTML/TeX and document-supplied attributes are removed.
4. Assemble pages in order, embed trusted figure bytes, and generate EPUB with
   tables, footnotes, table of contents and MathML. Pandoc runs with `--sandbox`.
5. Write results into a **new directory**. Temporary full-page images are cleaned
   up. Completed AI responses and their extracted figures are checkpointed privately
   so interrupted conversions can resume without repeating successful AI calls.

## Install

Use Python 3.13 and Pandoc 3.1.3 or newer (tested with 3.9).

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
```

`requirements.lock` pins direct and transitive Python dependencies. Install Pandoc
from your OS package manager or its official release packages.

## Run

```sh
export OPENAI_API_KEY="your-api-key"
.venv/bin/python pdf2reader.py book.pdf --epub
.venv/bin/python pdf2reader.py book.pdf --epub -o second-conversion -j 8
.venv/bin/python pdf2reader.py book.pdf --pages 1-5,9 --epub
```

Default output:

```text
book-output/
├── book.md
├── book.epub        # with --epub
└── p1-1.png         # extracted figures, when present
```

An existing output directory is never reused or recursively deleted. Choose a new
directory with `-o` for another completed conversion. A failed page stops export
rather than silently producing an incomplete book.

### Resume interrupted AI processing

Run the **same command again**. Successful page conversions and metadata requests
are reused; only missing or failed AI operations are retried. Cheap parsing and
EPUB assembly are repeated. Checkpoints are committed atomically after successful
responses, so an interrupted write is never mistaken for a completed page.

Checkpoints live in `<PDF name>-work/`, grouped by PDF SHA-256 content fingerprint,
model, pipeline version and rendering settings. Set `--work-dir PATH` to choose a
stable location if running from different working directories. Changing the PDF or
rendering settings starts a separate checkpoint set. Page selection, title, author
and output-directory changes reuse applicable successful page calls.

The private work directory contains extracted text and figure images; it persists
for resuming. Delete it yourself when no longer needed. An API call interrupted
before its result is saved may need to be repeated.

Options: `--dpi`, `--fig-dpi`, `--no-images`, `--title`, `--author`, `--pages`, `--work-dir`, `-j`.
Pandoc is required for both Markdown and EPUB output because validation uses its
document parser.

The program sends rendered pages and extracted text to OpenAI using your API key.
`store=False` is sent with every request. Final outputs remain in the directory you
choose. There is no web server, URL downloader, Readwise integration, Gmail access,
keychain access, configurable shell command, or remote deletion feature.

## Verification

```sh
.venv/bin/python -m unittest -v
```

Tests use a local API stub and synthetic PDFs; no paid model calls are made.
See [SECURITY_REVIEW.md](SECURITY_REVIEW.md) for the review scope and remaining limits.

## License

MIT. Forked from [lancejohnson/pdf2reader](https://github.com/lancejohnson/pdf2reader).
