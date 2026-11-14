"""Convert a local PDF to Markdown and EPUB with OpenAI GPT-6.1 Sol.

Usage: uv run pdf2reader book.pdf --epub [-o new-output-directory] [-j 2]
"""

import argparse
import datetime
import math
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

from dotenv import load_dotenv

from .pipeline import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", help="local PDF file")
    parser.add_argument("-o", "--out", help="new output directory (default: <PDF name>-output)")
    parser.add_argument("--work-dir", help="private resumable checkpoints (default: <PDF name>-work)")
    parser.add_argument("--epub", action="store_true")
    parser.add_argument("-j", "--jobs", type=int, default=2, help="parallel pages (default: 2)")
    parser.add_argument("--requests-per-minute", type=float, default=10,
                        help="shared request-start limit, including retries (default: 10)")
    for name in ("input", "cached-input", "output"):
        parser.add_argument(f"--{name}-price", type=float,
                            help=f"USD per million {name} tokens (or OPENAI_{name.upper().replace('-', '_')}_PRICE)")
    parser.add_argument("--dpi", type=int, default=170)
    parser.add_argument("--fig-dpi", type=int, default=200)
    parser.add_argument("--pages")
    parser.add_argument("--refresh-pages", help="reconvert these selected pages even if checkpointed (e.g. 37-38,72)")
    parser.add_argument("--no-images", dest="images", action="store_false")
    parser.add_argument("--title")
    parser.add_argument("--author")
    parser.add_argument("--date", help="publication date override (YYYY, YYYY-MM, or YYYY-MM-DD)")
    args = parser.parse_args()
    if args.date:
        try:
            if not re.fullmatch(r"\d{4}(?:-\d{2}){0,2}", args.date):
                raise ValueError
            datetime.date.fromisoformat(args.date + "-01" * (2 - args.date.count("-")))
        except ValueError:
            parser.error("date must be a valid YYYY, YYYY-MM, or YYYY-MM-DD")
    load_dotenv(pathlib.Path.cwd() / ".env")
    for name in ("input_price", "cached_input_price", "output_price"):
        if getattr(args, name) is None and os.environ.get(f"OPENAI_{name.upper()}"):
            try:
                setattr(args, name, float(os.environ[f"OPENAI_{name.upper()}"]))
            except ValueError:
                parser.error(f"OPENAI_{name.upper()} must be a number")
        price = getattr(args, name)
        if price is not None and (not math.isfinite(price) or price < 0):
            parser.error("token prices must be finite and nonnegative")
    if not math.isfinite(args.requests_per_minute) or args.requests_per_minute <= 0:
        parser.error("requests-per-minute must be finite and positive")
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("set OPENAI_API_KEY in .env or the environment")
    if not shutil.which("pandoc"):
        parser.error("install Pandoc 3.1.3 or newer with sandbox support")
    if min(args.jobs, args.dpi, args.fig_dpi) < 1:
        parser.error("jobs and image DPI must be positive")
    try:
        with tempfile.TemporaryDirectory(prefix="pdf2reader-") as work:
            run(args, pathlib.Path(work))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Conversion failed: {error}\n")
