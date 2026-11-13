"""Atomic checkpoint storage and PDF/settings fingerprints."""

import hashlib
import json
import os
import pathlib
import tempfile

from .openai_client import MODEL


def save_checkpoint(path, data):
    """Commit complete JSON atomically; interrupted writes are never reused."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = pathlib.Path(stream.name)
        try:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def checkpoint_directory(pdf, args):
    root = pathlib.Path(args.work_dir or f"{pdf.stem}-work").expanduser()
    settings = json.dumps([MODEL, args.dpi, args.fig_dpi, args.images, "pipeline-v2"]).encode()
    digest = hashlib.sha256(settings)
    with pdf.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    directory = root / digest.hexdigest()
    if root.is_symlink() or directory.is_symlink():
        raise ValueError("checkpoint directories must not be symlinks")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory
