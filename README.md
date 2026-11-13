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

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and
Pandoc 3.1.3 or newer (tested with the latest release, 3.14) from your OS package
manager or its official release packages.

```sh
uv sync --locked
```

uv automatically downloads Python 3.14.10 (pinned in `.python-version`) and creates
`.venv`. `pyproject.toml` declares dependencies and `uv.lock` pins the complete
dependency graph. Python 3.14 is required: the latest PyMuPDF depends on
ONNX Runtime, which does not yet publish Python 3.15 wheels. This is the newest
supported Python release for the current dependency stack.

## Run

```sh
cp .env.example .env
# Edit .env and set OPENAI_API_KEY to your API key.
uv run pdf2reader book.pdf --epub
uv run pdf2reader book.pdf --epub -o second-conversion -j 2
uv run pdf2reader book.pdf --pages 1-5,9 --epub
```

The CLI loads `.env` from the current working directory. Existing environment
variables take precedence. `.env` is ignored by Git.

### Request limits and live cost

The default is **two parallel pages** with request starts spaced at least six
seconds apart (**10 requests/minute**, shared across workers and retries).
Adjust with `-j` and `--requests-per-minute`. Rate limits and transient failures
get at most two retries with exponential backoff and jitter; `Retry-After` is
respected and pauses new requests across all workers. Actual token limits depend
on your OpenAI account and page size; lower concurrency/request rate if needed.

Every API response prints a running **estimated USD total** and token counts,
including cached input and reasoning output tokens. OpenAI responses supply token
usage, not a dollar charge. Built-in **GPT-6.1 Sol Standard** prices, verified
2026-11-13 in the [model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
are **$2 input, $0.10 cached input, and $10 output per million tokens**.
The API's default reasoning effort is **medium**; reasoning tokens are already
included in output usage and charged once at the output rate. Requests explicitly
select the default (Standard) service tier.

The estimate also includes [cache writes](https://developers.openai.com/api/docs/guides/prompt-caching)
at $2.50/M for 30-minute retention or $5/M for 12-hour retention, and the
long-context surcharge for requests above 272,000 input tokens (2× input/cache
rates and 1.5× output). Optional `.env` price overrides:

```sh
OPENAI_INPUT_PRICE=2
OPENAI_CACHED_INPUT_PRICE=0.10
OPENAI_OUTPUT_PRICE=10
```

Or use `--input-price`, `--cached-input-price`, and `--output-price`.
No configuration is needed to see dollar estimates. Usage is saved in `usage.json` inside
the checkpoint directory, so the total includes earlier runs and metadata calls;
reused page checkpoints add no cost. Rates supplied on the current run apply to
all recorded tokens. Older usage checkpoints lack cache-write/context breakdowns;
their historical tokens are estimated at ordinary short-context rates.
Responses with missing usage are counted separately, and
calls interrupted before usage is saved cannot be included. Totals update when
responses arrive, including incomplete responses, rather than while a response
is being generated. OpenAI billing remains the source of truth.

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
uv run --locked python -m unittest -v
```

Tests use a local API stub and synthetic PDFs; no paid model calls are made.
See [SECURITY_REVIEW.md](SECURITY_REVIEW.md) for the review scope and remaining limits.

## Development

The application lives in `src/pdf2reader` and is installed by `uv sync` in editable
mode. `uv run python -m pdf2reader` also runs the CLI.

```text
src/pdf2reader/
├── __init__.py       # package description
├── __main__.py       # python -m entry point
├── cli.py            # arguments, environment, and CLI errors
├── pipeline.py       # parallel conversion and book assembly
├── pages.py          # PDF rendering, figures, and page conversion
├── openai_client.py  # API requests, retries, and metadata extraction
├── budget.py         # shared rate limits and token cost accounting
├── checkpoints.py    # atomic storage and PDF/settings fingerprints
└── export.py         # Pandoc, sanitization, and image embedding
tests/
├── test_openai.py    # local API stub and budget tests
└── test_pipeline.py  # conversion, resume, and export security tests
```

The console entry point is `pdf2reader.cli:main`. Tests live outside the installed
package and are discovered by the verification command above.

```sh
uv add package-name          # add a runtime dependency
uv lock --upgrade           # update all locked dependencies
uv sync --locked
uv build                    # build a wheel and source distribution in dist/
```

## License

MIT. Forked from [lancejohnson/pdf2reader](https://github.com/lancejohnson/pdf2reader).
